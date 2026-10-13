"""Integration test against Testnet Bradbury, on the packed code that is deployed:

    python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
    cd tests/integration && gltest . -v -s --network testnet_bradbury   # config in this folder
"""

import json

import pytest
from gltest import get_accounts, get_contract_factory
from gltest.assertions import tx_execution_failed, tx_execution_succeeded

BUDGET = 10**15
OBJECTIVE = "Pay for public documentation hosting and domain renewal for an open-source project."
RUBRIC = json.dumps(["Spend serves the objective", "Evidence supports the spend"])


@pytest.mark.integration
def test_spend_and_review_with_real_consensus():
    guard = get_contract_factory("MandateGuard").deploy(args=[])
    agent = get_accounts()[1]
    assert tx_execution_succeeded(
        guard.grant(args=[agent.address, OBJECTIVE, RUBRIC, BUDGET // 2, 1, 86_400, ""]).transact(value=BUDGET)
    )
    as_agent = guard.connect(agent)
    vendor = get_accounts()[2].address
    assert tx_execution_succeeded(
        as_agent.spend(args=[0, vendor, BUDGET // 10, "Domain renewal", "https://www.iana.org/domains/reserved", ""]).transact()
    )
    # review_every = 1: further spending is blocked until reviewed.
    assert tx_execution_failed(as_agent.spend(args=[0, vendor, 1, "Another", "", ""]).transact())

    payouts = guard.get_payouts(args=[0]).call()
    assert payouts[0]["kind"] == "spend" and payouts[0]["status"] == "SENT"

    receipt = guard.request_review(args=[0]).transact(wait_interval=10_000, wait_retries=30)
    assert tx_execution_succeeded(receipt)
    reviews = guard.get_reviews(args=[0]).call()
    assert len(reviews) == 1
    assert reviews[0]["decision"] in {"continue", "warn", "constrain", "revoke", "escalate"}
