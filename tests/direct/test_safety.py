"""Adversarial cases: failed transfers, refunds, recipient controls, evidence integrity, repeated recovery."""

import hashlib

import pytest

from tests.direct.conftest import BUDGET, CAP, DAY, GEN, VENDOR, chain_balance, spend, to_hex, verdict

BODY = "Invoice: 4x A100 hours, $120"
SHA = hashlib.sha256(BODY.encode()).hexdigest()


def _review(vm, guard, decision, met=3, body=BODY):
    vm.clear_mocks()
    vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": body})
    verdict(vm, decision, met)
    return guard.request_review(0)


# ── Failed vendor payments ───────────────────────────────────────────────────


def test_delivered_payment_cannot_be_reconciled(guard, direct_vm, direct_bob, ledger):
    spend(direct_vm, guard, direct_bob)
    assert ledger.paid_to(VENDOR) == GEN
    chain_balance(direct_vm, BUDGET - GEN)  # the transfer left the contract
    assert guard.get_accounting()["unaccounted"] == 0
    direct_vm.warp("2030-01-03T00:00:00Z")
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("transfer delivered"):
        guard.reconcile_payout(0)


def test_failed_payment_returns_to_budget(guard, direct_vm, direct_alice, direct_bob, direct_charlie):
    spend(direct_vm, guard, direct_bob)  # chain balance stays at BUDGET: the transfer bounced
    assert guard.get_receipts(0)[0]["transfer"] == "SENT"
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("may still be settling"):
        guard.reconcile_payout(0)
    direct_vm.warp("2030-01-03T00:00:00Z")
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("not authorised"):
        guard.reconcile_payout(0)
    direct_vm.sender = direct_bob
    assert guard.reconcile_payout(0) == "budget"
    m = guard.get_mandate(0)
    assert m["budget"] == BUDGET and m["spent"] == 0
    assert guard.get_receipts(0)[0]["transfer"] == "FAILED"
    assert guard.get_accounting()["unaccounted"] == 0
    with direct_vm.expect_revert("already reconciled"):
        guard.reconcile_payout(0)
    # The receipt still counts toward review: validators see the attempt.
    assert m["spends_since_review"] == 1


def test_one_bounce_cannot_be_claimed_twice(guard, direct_vm, direct_bob):
    spend(direct_vm, guard, direct_bob)
    spend(direct_vm, guard, direct_bob)
    chain_balance(direct_vm, BUDGET - GEN)  # one of the two transfers failed
    direct_vm.warp("2030-01-03T00:00:00Z")
    direct_vm.sender = direct_bob
    guard.reconcile_payout(0)
    with direct_vm.expect_revert("transfer delivered"):
        guard.reconcile_payout(1)


def test_spend_reverts_when_contract_cannot_pay(guard, direct_vm, direct_bob, ledger):
    chain_balance(direct_vm, GEN // 2)
    with direct_vm.expect_revert("nothing was sent"):
        spend(direct_vm, guard, direct_bob)
    assert ledger.transfers == []
    m = guard.get_mandate(0)
    assert m["budget"] == BUDGET and m["receipt_count"] == 0


# ── Failed refunds never lose the delegator's entitlement ────────────────────


def _close_via(how, vm, guard, alice, bob):
    spend(vm, guard, bob)
    chain_balance(vm, BUDGET - GEN)
    if how == "emergency_revoke":
        vm.sender = alice
        return guard.emergency_revoke(0)
    if how == "expiry":
        vm.warp("2030-02-05T00:00:00Z")
        vm.sender = alice
        return guard.withdraw_remaining(0)
    _review(vm, guard, "escalate", met=1)
    vm.sender = alice
    return guard.resolve_escalation(0, False)


@pytest.mark.parametrize("how", ["emergency_revoke", "expiry", "escalation_close"])
def test_failed_refund_is_recoverable(how, guard, direct_vm, direct_alice, direct_bob, direct_charlie, ledger):
    _close_via(how, direct_vm, guard, direct_alice, direct_bob)
    assert ledger.paid_to(direct_alice) == BUDGET - GEN
    refund = guard.get_payouts(0)[-1]
    assert refund["kind"] == "refund" and refund["status"] == "SENT"
    # The refund bounced: the contract still holds it.
    direct_vm.warp("2030-03-01T00:00:00Z")
    direct_vm.sender = direct_alice
    assert guard.reconcile_payout(refund["id"]) == "recoverable"
    assert guard.get_mandate(0)["recoverable"] == BUDGET - GEN
    with direct_vm.expect_revert("not authorised"):
        direct_vm.sender = direct_bob
        guard.recover(0, to_hex(direct_bob))
    direct_vm.sender = direct_alice
    assert guard.recover(0, to_hex(direct_charlie)) == BUDGET - GEN
    assert ledger.paid_to(direct_charlie) == BUDGET - GEN
    with direct_vm.expect_revert("nothing to recover"):
        guard.recover(0, to_hex(direct_charlie))
    with direct_vm.expect_revert("mandate is closed"):
        guard.emergency_revoke(0)


def test_bounced_spend_after_close_goes_to_delegator(guard, direct_vm, direct_alice, direct_bob):
    spend(direct_vm, guard, direct_bob)  # bounces: balance stays BUDGET
    direct_vm.sender = direct_alice
    guard.emergency_revoke(0)  # refund of BUDGET-GEN delivered
    chain_balance(direct_vm, GEN)
    direct_vm.warp("2030-01-03T00:00:00Z")
    assert guard.reconcile_payout(0) == "recoverable"
    assert guard.get_mandate(0)["recoverable"] == GEN


# ── Unauthorized spends and recipient controls ──────────────────────────────


def test_unauthorized_and_self_dealing_spends(guard, direct_vm, direct_alice, direct_bob, direct_charlie):
    for who in (direct_alice, direct_charlie):
        with direct_vm.expect_revert("not authorised"):
            spend(direct_vm, guard, who)
    with direct_vm.expect_revert("cannot pay itself"):
        spend(direct_vm, guard, direct_bob, to=to_hex(direct_bob))
    with direct_vm.expect_revert("cannot pay itself"):
        spend(direct_vm, guard, direct_bob, to=to_hex(direct_vm._contract_address))


def test_recipient_allowlist(guard, direct_vm, direct_alice, direct_bob, direct_charlie):
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("not authorised"):
        guard.set_recipients(0, f'["{VENDOR}"]')
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("agent cannot be a recipient"):
        guard.set_recipients(0, f'["{to_hex(direct_bob)}"]')
    guard.set_recipients(0, f'["{VENDOR}"]')
    with direct_vm.expect_revert("not on the mandate allowlist"):
        spend(direct_vm, guard, direct_bob, to=to_hex(direct_charlie))
    spend(direct_vm, guard, direct_bob)
    direct_vm.sender = direct_alice
    guard.set_recipients(0, "[]")
    spend(direct_vm, guard, direct_bob, to=to_hex(direct_charlie))


# ── Evidence integrity ───────────────────────────────────────────────────────


def test_commitment_match_is_recorded(guard, direct_vm, direct_bob):
    spend(direct_vm, guard, direct_bob, sha=SHA)
    _review(direct_vm, guard, "continue")
    ev = guard.get_reviews(0)[0]["evidence"][0]
    assert ev == {"status": "match", "sha256": SHA, "chars": len(BODY)}


def test_edited_evidence_is_flagged_and_binds_validators(guard, direct_vm, direct_bob):
    spend(direct_vm, guard, direct_bob, sha=SHA)
    _review(direct_vm, guard, "continue")
    # A validator fetching an edited page sees a different status and must disagree.
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": BODY + " (edited)"})
    verdict(direct_vm, "continue")
    assert direct_vm.run_validator() is False


def test_changed_and_unavailable_evidence(guard, direct_vm, direct_bob):
    import gltest.direct.wasi_mock as wm

    spend(direct_vm, guard, direct_bob, sha=SHA)
    spend(direct_vm, guard, direct_bob, url="https://gone.example.org/x")
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": "rewritten"})
    seen = {}
    orig = wm._handle_llm_request

    def spy(vm, data):
        seen["prompt"] = data["prompt"]
        return {"ok": {"decision": "escalate", "criteria": [], "violations": [], "reasoning": "x"}}

    wm._handle_llm_request = spy
    try:
        guard.request_review(0)
    finally:
        wm._handle_llm_request = orig
    assert "[CHANGED:" in seen["prompt"] and "[UNAVAILABLE]" in seen["prompt"]
    assert [e["status"] for e in guard.get_reviews(0)[0]["evidence"]] == ["changed", "unavailable"]


def test_truncation_is_explicit(guard, direct_vm, direct_bob):
    import gltest.direct.wasi_mock as wm

    spend(direct_vm, guard, direct_bob)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": "x" * 5000})
    seen = {}
    orig = wm._handle_llm_request

    def spy(vm, data):
        seen["prompt"] = data["prompt"]
        return {"ok": {"decision": "escalate", "criteria": [], "violations": [], "reasoning": "x"}}

    wm._handle_llm_request = spy
    try:
        guard.request_review(0)
    finally:
        wm._handle_llm_request = orig
    assert "[TRUNCATED: first 3000 of 5000 characters shown]" in seen["prompt"]
    assert guard.get_reviews(0)[0]["evidence"][0]["chars"] == 5000


def test_bad_commitment_rejected(guard, direct_vm, direct_bob):
    with direct_vm.expect_revert("64 hex"):
        spend(direct_vm, guard, direct_bob, sha="abc")
    with direct_vm.expect_revert("64 hex"):
        spend(direct_vm, guard, direct_bob, url="", sha=SHA)


# ── Repeated recovery ────────────────────────────────────────────────────────


def test_repeated_overrides_never_look_like_clearance(guard, direct_vm, direct_alice, direct_bob):
    for _ in range(2):
        spend(direct_vm, guard, direct_bob, amount=CAP // 2)
        _review(direct_vm, guard, "escalate", met=1)
        direct_vm.sender = direct_alice
        guard.resolve_escalation(0, True)
        assert guard.get_mandate(0)["status"] == "CONSTRAINED"
    reviews = guard.get_reviews(0)
    assert [r["decision"] for r in reviews] == ["escalate", "override"] * 2
    assert [r["source"] for r in reviews] == ["validators", "delegator"] * 2
    assert guard.get_agent_record(to_hex(direct_bob)) == {"reviews_passed": 0, "revocations": 0}
    with direct_vm.expect_revert("not escalated"):
        guard.resolve_escalation(0, True)


def test_conflicting_validators_cannot_finalize_a_revoke(guard, direct_vm, direct_bob):
    """Leader says revoke, honest validators read the same evidence as fine."""
    spend(direct_vm, guard, direct_bob)
    _review(direct_vm, guard, "continue")
    stored = direct_vm._captured_validators[-1][0]
    assert direct_vm.run_validator(leader_result={**stored, "decision": "revoke"}) is False
    assert direct_vm.run_validator(leader_result={**stored, "decision": "warn"}) is False
    assert direct_vm.run_validator(leader_result={**stored, "evidence": []}) is False
