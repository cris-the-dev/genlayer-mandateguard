"""Adversarial cases: failed transfers, refunds, recipient controls, evidence integrity, repeated recovery."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.direct.conftest import BUDGET, CAP, DAY, GEN, OBJECTIVE, RUBRIC, VENDOR, chain_balance, spend, to_hex, verdict

MILLI = 10**15

BODY = "Invoice: 4x A100 hours, $120"
SHA = hashlib.sha256(BODY.encode()).hexdigest()


def _review(vm, guard, decision, met=3, body=BODY):
    vm.clear_mocks()
    vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": body})
    verdict(vm, decision, met)
    return guard.request_review(0)


# ── Each payout settles from its own transfer result ────────────────────────


def _spend_call(amount=GEN, to=VENDOR):
    return ["spend", [0, to, amount, "Rent GPU hours for training", "https://evidence.example.com/inv/1", ""]]


def test_delivered_payment_settles_delivered(guard, direct_vm, direct_bob, direct_charlie, ledger, chain):
    spend(direct_vm, guard, direct_bob)
    assert ledger.paid_to(VENDOR) == GEN
    tx, fin = chain.pay(guard, 0, *_spend_call())
    direct_vm.sender = direct_charlie  # anyone can settle
    assert guard.settle_payout(0, tx, fin) == "DELIVERED"
    p = guard.get_payouts(0)[0]
    assert p["status"] == "DELIVERED" and p["tx"] == tx
    assert guard.get_mandate(0)["budget"] == BUDGET - GEN
    with direct_vm.expect_revert("already settled"):
        guard.settle_payout(0, tx, fin)
    # Validators re-read the chain: a leader claiming "failed" is rejected.
    assert direct_vm.run_validator(leader_result="failed") is False
    assert direct_vm.run_validator(leader_result="delivered") is True


def test_failed_payment_returns_to_budget(guard, direct_vm, direct_bob, chain):
    spend(direct_vm, guard, direct_bob)
    assert guard.get_receipts(0)[0]["transfer"] == "SENT"
    tx, fin = chain.pay(guard, 0, *_spend_call(), delivered=False)
    assert guard.settle_payout(0, tx, fin) == "budget"
    m = guard.get_mandate(0)
    assert m["budget"] == BUDGET and m["spent"] == 0
    assert guard.get_receipts(0)[0]["transfer"] == "FAILED"
    assert guard.get_accounting()["expected_balance"] == BUDGET
    assert direct_vm.run_validator(leader_result="delivered") is False
    # The receipt still counts toward review: validators see the attempt.
    assert m["spends_since_review"] == 1


def test_one_bounce_is_tied_to_its_own_payout(guard, direct_vm, direct_bob, chain):
    spend(direct_vm, guard, direct_bob)
    spend(direct_vm, guard, direct_bob)
    tx0, fin0 = chain.pay(guard, 0, *_spend_call(), delivered=False)
    tx1, fin1 = chain.pay(guard, 1, *_spend_call())
    # A paying transaction settles only the payout it created, and only once.
    with direct_vm.expect_revert("did not create this payout"):
        guard.settle_payout(1, tx0, fin0)
    assert guard.settle_payout(0, tx0, fin0) == "budget"
    with direct_vm.expect_revert("already settled a payout"):
        guard.settle_payout(1, tx0, fin0)
    assert guard.settle_payout(1, tx1, fin1) == "DELIVERED"
    assert guard.get_mandate(0)["spent"] == GEN


@pytest.mark.parametrize(
    "case, kw, err",
    [
        ("other sender", {"sender": "0x" + "77" * 20}, "did not create this payout"),
        ("other time", {"at": 1}, "did not create this payout"),
        ("other contract", {"contract": "0x" + "88" * 20}, "did not create this payout"),
        ("reverted tx", {"result": 2}, "did not create this payout"),
        ("other method", {"method": "request_review", "args": [0]}, "did not create this payout"),
        ("other amount", {"args": _spend_call(GEN // 2)[1]}, "did not create this payout"),
        ("other recipient", {"args": _spend_call(to="0x" + "99" * 20)[1]}, "did not create this payout"),
        ("not finalized", {"status": 5}, "not finalized yet"),
    ],
)
def test_settle_rejects_a_transaction_that_is_not_this_payout(case, kw, err, guard, direct_vm, direct_bob, chain):
    spend(direct_vm, guard, direct_bob)
    method, args = kw.pop("method", "spend"), kw.pop("args", _spend_call()[1])
    tx, fin = chain.pay(guard, 0, method, args, delivered=False, **kw)
    with direct_vm.expect_revert(err):
        guard.settle_payout(0, tx, fin)
    assert guard.get_payouts(0)[0]["status"] == "SENT"


def test_settle_needs_the_finalization_of_that_transaction(guard, direct_vm, direct_bob, chain):
    spend(direct_vm, guard, direct_bob)
    spend(direct_vm, guard, direct_bob)
    tx0, _ = chain.pay(guard, 0, *_spend_call(), delivered=False)
    _, fin1 = chain.pay(guard, 1, *_spend_call())
    with direct_vm.expect_revert("not the finalization"):
        guard.settle_payout(0, tx0, fin1)
    with direct_vm.expect_revert("not found"):
        guard.settle_payout(0, tx0, "0x" + "ab" * 32)
    with direct_vm.expect_revert("0x + 64 hex"):
        guard.settle_payout(0, tx0, "latest")
    chain.down = True
    with direct_vm.expect_revert("RPC unavailable"):
        guard.settle_payout(0, tx0, fin1)


def test_recorded_bradbury_transfer_settles_delivered(direct_vm, direct_deploy, direct_alice, chain):
    """Replays real Bradbury responses: the spend that created payout #2 on the
    previous deployment and the consensus transaction that finalized it."""
    rec = json.loads(Path(__file__).with_name("bradbury_payout.json").read_text())
    direct_vm.warp("2026-10-13T06:18:05Z")  # the spend's creation time, 1791872285
    guard = direct_deploy("contracts/mandate_guard.py")
    from genlayer.py.types import Address

    agent = Address("0x93d35654b6c67778fed97dd72ae6d83846759088")
    direct_vm.sender = direct_alice
    direct_vm.value = 4 * MILLI
    for _ in range(2):
        guard.grant(agent.as_hex, OBJECTIVE, RUBRIC, 2 * MILLI, 1, 30 * DAY, "")
    direct_vm.value = 0
    chain_balance(direct_vm, 4 * MILLI)
    direct_vm.sender = agent
    guard.spend(1, "0xf5792e917414548f44f197347eb8bb05814bb350", MILLI, "Bounty", "", "")
    assert guard.get_payouts(1)[0]["at"] == rec["gen_getTransactionReceipt"]["timestamps"]["Created"]

    # The recorded contract address becomes this test's contract; everything else is as recorded.
    raw = json.dumps(rec).replace("637301a7bc5f8b0b0e8bd6ac858894ac94761bd3", to_hex(direct_vm._contract_address).lower()[2:])
    rec = json.loads(raw)
    fin = rec["eth_getTransactionReceipt"]["transactionHash"]
    chain.receipts[("gen_getTransactionReceipt", rec["tx"])] = rec["gen_getTransactionReceipt"]
    chain.receipts[("eth_getTransactionReceipt", fin)] = rec["eth_getTransactionReceipt"]
    assert guard.settle_payout(0, rec["tx"], fin) == "DELIVERED"

    # Without the ghost's TransactionExecuted log the same finalization reads as failed.
    chain.receipts[("eth_getTransactionReceipt", fin)]["logs"] = [
        lg for lg in rec["eth_getTransactionReceipt"]["logs"] if not lg["topics"][0].startswith("0x4aacc176")
    ]
    assert direct_vm.run_validator(leader_result="delivered") is False


def test_one_payment_per_sender_per_second(guard, direct_vm, direct_bob):
    spend(direct_vm, guard, direct_bob)
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("one payment per sender per second"):
        guard.spend(0, VENDOR, GEN, "Rent GPU hours for training", "https://evidence.example.com/inv/1", "")


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
def test_failed_refund_is_recoverable(how, guard, direct_vm, direct_alice, direct_bob, direct_charlie, ledger, chain):
    _close_via(how, direct_vm, guard, direct_alice, direct_bob)
    assert ledger.paid_to(direct_alice) == BUDGET - GEN
    refund = guard.get_payouts(0)[-1]
    assert refund["kind"] == "refund" and refund["status"] == "SENT"
    call = {"emergency_revoke": ["emergency_revoke", [0]], "expiry": ["withdraw_remaining", [0]]}
    # A close that restored the mandate sends nothing, so it cannot be presented as a refund.
    if how == "escalation_close":
        tx, fin = chain.pay(guard, refund["id"], "resolve_escalation", [0, True], delivered=False)
        with direct_vm.expect_revert("did not create this payout"):
            guard.settle_payout(refund["id"], tx, fin)
    tx, fin = chain.pay(guard, refund["id"], *call.get(how, ["resolve_escalation", [0, False]]), delivered=False)
    direct_vm.warp("2030-03-01T00:00:00Z")
    direct_vm.sender = direct_alice
    assert guard.settle_payout(refund["id"], tx, fin) == "recoverable"
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


def test_bounced_spend_after_close_goes_to_delegator(guard, direct_vm, direct_alice, direct_bob, chain):
    spend(direct_vm, guard, direct_bob)
    direct_vm.sender = direct_alice
    guard.emergency_revoke(0)
    tx, fin = chain.pay(guard, 0, *_spend_call(), delivered=False)
    assert guard.settle_payout(0, tx, fin) == "recoverable"
    assert guard.get_mandate(0)["recoverable"] == GEN
    # The recovery itself is a payout settled the same way.
    direct_vm.warp("2030-01-03T00:00:00Z")
    guard.recover(0, VENDOR)
    rec = guard.get_payouts(0)[-1]
    tx, fin = chain.pay(guard, rec["id"], "recover", [0, VENDOR])
    assert guard.settle_payout(rec["id"], tx, fin) == "DELIVERED"


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


def test_http_error_is_unavailable(guard, direct_vm, direct_bob):
    spend(direct_vm, guard, direct_bob)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 404, "body": "Not Found"})
    verdict(direct_vm, "escalate", 1)
    guard.request_review(0)
    assert guard.get_reviews(0)[0]["evidence"][0]["status"] == "unavailable"
