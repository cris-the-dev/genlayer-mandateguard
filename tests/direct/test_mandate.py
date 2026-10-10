"""Mandate lifecycle: authority limits, review gating, decisions, appeals, safety switches."""

import pytest

from tests.direct.conftest import (
    BUDGET,
    CAP,
    DAY,
    GEN,
    OBJECTIVE,
    RUBRIC,
    VENDOR,
    spend,
    to_hex,
    verdict,
)

# ── Grant ────────────────────────────────────────────────────────────────────


def test_grant(guard, direct_alice, direct_bob):
    m = guard.get_mandate(0)
    assert m["delegator"] == to_hex(direct_alice) and m["agent"] == to_hex(direct_bob)
    assert m["budget"] == BUDGET and m["effective_max_per_tx"] == CAP
    assert m["status"] == "ACTIVE" and m["permission_ref"] == "erc7710:0xabc"
    assert guard.get_mandate_count() == 1


def test_grant_validation(guard, direct_vm, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    b = to_hex(direct_bob)
    with direct_vm.expect_revert("budget must be greater than zero"):
        guard.grant(b, OBJECTIVE, RUBRIC, CAP, 2, DAY, "")
    direct_vm.value = GEN
    with direct_vm.expect_revert("agent must differ"):
        guard.grant(to_hex(direct_alice), OBJECTIVE, RUBRIC, 1, 2, DAY, "")
    with direct_vm.expect_revert("max_per_tx must be"):
        guard.grant(b, OBJECTIVE, RUBRIC, 2 * GEN, 2, DAY, "")
    with direct_vm.expect_revert("rubric must have"):
        guard.grant(b, OBJECTIVE, "[]", 1, 2, DAY, "")
    with direct_vm.expect_revert("review_every must be"):
        guard.grant(b, OBJECTIVE, RUBRIC, 1, 11, DAY, "")
    direct_vm.value = 0


# ── Spending ─────────────────────────────────────────────────────────────────


def test_agent_spends_with_receipt(guard, direct_vm, direct_bob, ledger):
    assert spend(direct_vm, guard, direct_bob) == 0
    assert ledger.paid_to(VENDOR) == GEN
    m = guard.get_mandate(0)
    assert m["budget"] == BUDGET - GEN and m["spent"] == GEN
    r = guard.get_receipts(0)[0]
    assert r["to"].lower() == VENDOR and r["purpose"].startswith("Rent GPU")
    spent_event = ledger.events[-1]
    assert to_hex(spent_event["agent"]) == to_hex(direct_bob) and int(spent_event["mandate_id"]) == 0


def test_hard_limits_never_depend_on_the_llm(guard, direct_vm, direct_alice, direct_bob):
    with direct_vm.expect_revert("not authorised"):
        spend(direct_vm, guard, direct_alice)
    with direct_vm.expect_revert("per-transaction cap"):
        spend(direct_vm, guard, direct_bob, amount=CAP + 1)
    with direct_vm.expect_revert("evidence must be an https URL"):
        spend(direct_vm, guard, direct_bob, url="http://plain")
    with direct_vm.expect_revert("purpose must be"):
        spend(direct_vm, guard, direct_bob, purpose="")


def test_review_gating(guard, direct_vm, direct_bob, direct_charlie):
    spend(direct_vm, guard, direct_bob)
    spend(direct_vm, guard, direct_bob)
    assert guard.get_mandate(0)["review_due"] is True
    with direct_vm.expect_revert("review due"):
        spend(direct_vm, guard, direct_bob)
    verdict(direct_vm, "continue")
    direct_vm.sender = direct_charlie  # anyone (a keeper) may trigger reviews
    assert guard.request_review(0)["decision"] == "continue"
    spend(direct_vm, guard, direct_bob)  # unblocked


def test_nothing_to_review(guard, direct_vm):
    with direct_vm.expect_revert("nothing to review"):
        guard.request_review(0)


# ── Decisions ────────────────────────────────────────────────────────────────


def _review(direct_vm, guard, agent, decision, met=3):
    spend(direct_vm, guard, agent)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": "invoice"})
    verdict(direct_vm, decision, met)
    return guard.request_review(0)


def test_warn_then_warn_escalates_to_constrain(guard, direct_vm, direct_bob):
    _review(direct_vm, guard, direct_bob, "warn")
    assert guard.get_mandate(0)["status"] == "WARNED"
    _review(direct_vm, guard, direct_bob, "warn")
    m = guard.get_mandate(0)
    assert m["status"] == "CONSTRAINED" and m["effective_max_per_tx"] == CAP // 2
    assert [r["decision"] for r in guard.get_reviews(0)] == ["warn", "constrain"]


def test_constrained_requires_evidence_and_half_cap(guard, direct_vm, direct_bob):
    _review(direct_vm, guard, direct_bob, "constrain")
    with direct_vm.expect_revert("require evidence"):
        spend(direct_vm, guard, direct_bob, url="")
    with direct_vm.expect_revert("per-transaction cap"):
        spend(direct_vm, guard, direct_bob, amount=CAP // 2 + 1)
    spend(direct_vm, guard, direct_bob, amount=CAP // 2)
    # A later clean review restores full authority.
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": "invoice"})
    verdict(direct_vm, "continue")
    guard.request_review(0)
    assert guard.get_mandate(0)["effective_max_per_tx"] == CAP


def test_revoke_freezes_then_delegator_withdraws(guard, direct_vm, direct_alice, direct_bob, ledger):
    _review(direct_vm, guard, direct_bob, "revoke", met=0)
    assert guard.get_mandate(0)["status"] == "REVOKED"
    with direct_vm.expect_revert("spending is frozen"):
        spend(direct_vm, guard, direct_bob)
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("still live"):
        guard.withdraw_remaining(0)  # agent's appeal window is open
    direct_vm.warp("2030-01-04T00:00:00Z")
    assert guard.withdraw_remaining(0) == BUDGET - GEN
    assert ledger.paid_to(direct_alice) == BUDGET - GEN
    assert guard.get_agent_record(to_hex(direct_bob)) == {"reviews_passed": 0, "revocations": 1}
    assert "revoke" in ledger.decisions() and "close" in ledger.decisions()


def test_successful_appeal_restores_authority(guard, direct_vm, direct_bob):
    _review(direct_vm, guard, direct_bob, "revoke", met=0)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": "invoice"})
    verdict(direct_vm, "continue", pattern=r"THIS IS AN APPEAL")
    direct_vm.sender = direct_bob
    r = guard.appeal_revocation(0, "The GPU rental is the core of the training objective; see invoice.")
    assert r["decision"] == "continue"
    m = guard.get_mandate(0)
    assert m["status"] == "ACTIVE" and m["appealed"] is True
    assert guard.get_agent_record(to_hex(direct_bob))["revocations"] == 0
    assert guard.get_reviews(0)[-1]["appeal"] is True
    with direct_vm.expect_revert("not revoked"):
        guard.appeal_revocation(0, "Second appeal attempt should be rejected here.")


def test_failed_appeal_is_final(guard, direct_vm, direct_alice, direct_bob):
    _review(direct_vm, guard, direct_bob, "revoke", met=0)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": "invoice"})
    verdict(direct_vm, "revoke", met=0)
    direct_vm.sender = direct_bob
    guard.appeal_revocation(0, "Please reconsider the decision, the spend was legitimate.")
    assert guard.get_agent_record(to_hex(direct_bob))["revocations"] == 1  # not double counted
    with direct_vm.expect_revert("already appealed"):
        guard.appeal_revocation(0, "Trying a second appeal to re-roll the decision.")
    direct_vm.sender = direct_alice
    assert guard.withdraw_remaining(0) == BUDGET - GEN  # no need to wait after a failed appeal


def test_appeal_window(guard, direct_vm, direct_bob):
    _review(direct_vm, guard, direct_bob, "revoke", met=0)
    direct_vm.warp("2030-01-04T00:00:00Z")
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("appeal window closed"):
        guard.appeal_revocation(0, "Too late, but trying anyway with enough characters.")


def test_escalate_hands_control_to_delegator(guard, direct_vm, direct_alice, direct_bob, ledger):
    _review(direct_vm, guard, direct_bob, "escalate", met=1)
    assert guard.get_mandate(0)["status"] == "ESCALATED"
    with direct_vm.expect_revert("spending is frozen"):
        spend(direct_vm, guard, direct_bob)
    direct_vm.sender = direct_alice
    guard.resolve_escalation(0, True)
    assert guard.get_mandate(0)["status"] == "ACTIVE"
    assert "restore" in ledger.decisions()


def test_escalate_then_delegator_closes(guard, direct_vm, direct_alice, direct_bob, ledger):
    _review(direct_vm, guard, direct_bob, "escalate", met=1)
    direct_vm.sender = direct_alice
    guard.resolve_escalation(0, False)
    assert guard.get_mandate(0)["status"] == "CLOSED"
    assert ledger.paid_to(direct_alice) == BUDGET - GEN


# ── Delegator safety switches ────────────────────────────────────────────────


def test_emergency_revoke_any_time(guard, direct_vm, direct_alice, direct_bob, ledger):
    spend(direct_vm, guard, direct_bob)
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("not authorised"):
        guard.emergency_revoke(0)
    direct_vm.sender = direct_alice
    assert guard.emergency_revoke(0) == BUDGET - GEN
    assert guard.get_mandate(0)["status"] == "CLOSED"
    with direct_vm.expect_revert("spending is frozen"):
        spend(direct_vm, guard, direct_bob)


def test_expiry(guard, direct_vm, direct_alice, direct_bob):
    direct_vm.warp("2030-02-05T00:00:00Z")
    with direct_vm.expect_revert("mandate expired"):
        spend(direct_vm, guard, direct_bob)
    direct_vm.sender = direct_alice
    assert guard.withdraw_remaining(0) == BUDGET


def test_top_up(guard, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    direct_vm.value = GEN
    guard.top_up(0)
    direct_vm.value = 0
    assert guard.get_mandate(0)["budget"] == BUDGET + GEN


@pytest.mark.parametrize("decision", ["continue", "warn", "constrain", "revoke", "escalate"])
def test_decision_event_carries_permission_ref(guard, direct_vm, direct_bob, ledger, decision):
    _review(direct_vm, guard, direct_bob, decision)
    ev = [e for e in ledger.events if e.get("decision") == decision][-1]
    assert ev["permission_ref"] == "erc7710:0xabc"
    assert to_hex(ev["agent"]) == to_hex(direct_bob) and int(ev["mandate_id"]) == 0
