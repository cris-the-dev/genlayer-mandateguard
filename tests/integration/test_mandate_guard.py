"""End-to-end on Testnet Bradbury, on the packed code that is deployed:

    python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
    cd tests/integration && gltest . -v -s --network testnet_bradbury   # config in this folder

Accounts: GL_PK0 delegator, GL_PK1 agent, GL_PK2 vendor. Runs for about an hour:
value transfers execute when each paying transaction finalizes (~30 min).

Covers, with real validators and real transfers:
- mandate 0: warn -> constrain (restrictions enforced) -> revoke -> appeal (upheld)
  -> refund; every spend and the refund settled DELIVERED from its own transfer,
  with the recipient's balance rising by exactly the payout in the finalizing block;
- mandate 1: a spend to an EVM contract that rejects value settles FAILED, the
  recipient's balance does not move and the amount returns to the budget.
"""

import json
import time
from pathlib import Path
import urllib.error
import urllib.request

import pytest
from eth_account import Account
from gltest import get_accounts
from gltest.contracts.contract_factory import ContractFactory
from gltest.clients import get_gl_client

RPC = "https://rpc-bradbury.genlayer.com"
CHAIN_ID = 4221
CONSENSUS_MAIN = "0x0112Bf6e83497965A5fdD6Dad1E447a6E004271D"
T_FINALIZED = "0x24196ec40f90671b7144e716978686b4f3c7d6b00b23da3971ef2b52af27d87f"

MILLI = 10**15  # 0.001 GEN
REPO = "https://raw.githubusercontent.com/cris-the-dev/genlayer-mandateguard/main"
OBJECTIVE = "Pay contributors for documentation, examples and tests of the MandateGuard open-source repository."
RUBRIC = json.dumps(
    [
        "Each spend pays for documentation, examples or tests of this repository",
        "Each spend is at most 0.001 GEN (1000000000000000 wei)",
        "Each spend's purpose names the contributor's GitHub handle",
    ]
)
# Runtime code PUSH1 0 PUSH1 0 REVERT: rejects every call, including plain value.
REJECTER_INITCODE = "0x6460006000fd6000526005601bf3"

S = {}  # state shared by the ordered steps below


def rpc(method, params):
    req = urllib.request.Request(
        RPC,
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},  # the RPC rejects Python's default agent
    )
    for attempt in range(5):  # the edge returns occasional 5xx over an hour-long run
        try:
            out = json.load(urllib.request.urlopen(req, timeout=60))
            break
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 4:
                raise
            time.sleep(10)
    if "error" in out:
        raise RuntimeError(f"{method}: {out['error']}")
    return out["result"]


def view(fn, args=()):
    """Raw gen_call: genlayer_py's read_contract does not parse Bradbury's response."""
    from genlayer_py.abi import calldata
    from genlayer_py.abi.transactions import serialize
    from genlayer_py.contracts.utils import make_calldata_object

    data = serialize([calldata.encode(make_calldata_object(method=fn, args=list(args), kwargs=None)), b"\x00"])
    r = get_gl_client().provider.make_request(
        method="gen_call",
        params=[{"type": "read", "to": S["guard"].address, "from": S["delegator"].address, "data": data, "transaction_hash_variant": "latest-nonfinal"}],
    )["result"]
    if isinstance(r, dict):
        r = r.get("data") or r.get("result")
    return calldata.decode(bytes.fromhex(r.removeprefix("0x")))


def _result(receipt):
    """(tx id, txExecutionResult) from the chain: gltest's assertions only read Studio receipts."""
    tx = receipt.get("tx_id") or receipt.get("hash")
    return tx, rpc("gen_getTransactionReceipt", [{"txId": tx}])["txExecutionResult"]


def ok(receipt):
    tx, res = _result(receipt)
    assert res == 1, f"{tx} execution result {res}"
    return tx


def reverted(receipt):
    tx, res = _result(receipt)
    return res == 2


def balance(addr, block):
    return int(rpc("eth_getBalance", [addr, hex(block)]), 16)


def finalization(tx, timeout=3 * 3600):
    """Wait until GenLayer tx `tx` is finalized; return the consensus-layer tx that finalized it."""
    deadline = time.time() + timeout
    while True:
        r = rpc("gen_getTransactionReceipt", [{"txId": tx}])
        if r and r.get("status") == 7:
            break
        assert time.time() < deadline, f"{tx} not finalized: {r and r.get('status')}"
        time.sleep(30)
    start = int(r["readStateBlockRanges"][0]["ProposalBlock"])
    head = int(rpc("eth_blockNumber", []), 16)
    for lo in range(start, head + 1, 10_000):
        logs = rpc(
            "eth_getLogs",
            [{"address": CONSENSUS_MAIN, "topics": [T_FINALIZED, tx], "fromBlock": hex(lo), "toBlock": hex(min(lo + 9_999, head))}],
        )
        if logs:
            return logs[0]["transactionHash"], int(logs[0]["blockNumber"], 16)
    raise AssertionError(f"no TransactionFinalized log for {tx}")


def deploy_rejecter(key):
    acct = Account.from_key(key)
    tx = {
        "chainId": CHAIN_ID,
        "nonce": int(rpc("eth_getTransactionCount", [acct.address, "pending"]), 16),
        "gas": 100_000,
        "gasPrice": int(rpc("eth_gasPrice", []), 16),
        "data": REJECTER_INITCODE,
        "value": 0,
    }
    h = rpc("eth_sendRawTransaction", ["0x" + acct.sign_transaction(tx).raw_transaction.hex().removeprefix("0x")])
    for _ in range(60):
        rc = rpc("eth_getTransactionReceipt", [h])
        if rc:
            assert rc["status"] == "0x1" and rc["contractAddress"], rc
            return rc["contractAddress"]
        time.sleep(5)
    raise AssertionError(f"rejecter deploy {h} not mined")


def review(mid):
    ok(S["guard"].request_review(args=[mid]).transact(wait_interval=10_000, wait_retries=60))
    return view("get_reviews", [mid])[-1]


def spend(mid, to, amount, purpose, url):
    tx = ok(S["agent_guard"].spend(args=[mid, to, amount, purpose, url, ""]).transact())
    S["paid"].append((mid, tx, view("get_payouts", [mid])[-1]))


pytestmark = pytest.mark.integration


def test_setup():
    S["delegator"], agent, vendor = get_accounts()[:3]
    S["vendor"] = vendor.address
    # The packed build hides the class inside exec(), so gltest's AST lookup cannot find it by name.
    code = (Path(__file__).parents[2] / "build" / "mandate_guard.py").read_text()
    factory = ContractFactory(contract_name="MandateGuard", contract_code=code)
    receipt = factory.deploy_contract_tx(args=[])
    ok(receipt)
    S["guard"] = factory.build_contract(contract_address=receipt["recipient"])  # Bradbury: the new contract
    S["agent_guard"] = S["guard"].connect(agent)
    S["paid"] = []
    # Mandate 0: the supervision lifecycle. Mandate 1: a transfer that fails.
    ok(S["guard"].grant(args=[agent.address, OBJECTIVE, RUBRIC, 2 * MILLI, 1, 7 * 86_400, "erc7710:e2e"]).transact(value=5 * MILLI))
    ok(S["guard"].grant(args=[agent.address, OBJECTIVE, RUBRIC, MILLI, 5, 7 * 86_400, ""]).transact(value=MILLI))
    S["rejecter"] = deploy_rejecter(S["delegator"].key.hex())
    print("contract", S["guard"].address, "rejecter", S["rejecter"])


def test_warn():
    # Serves the objective, but the purpose does not name the contributor (criterion 3).
    spend(0, S["vendor"], MILLI, "Payment for the adversarial test suite", f"{REPO}/tests/direct/test_safety.py")
    r = review(0)
    assert r["decision"] == "warn", r
    assert view("get_mandate", [0])["status"] == "WARNED"


def test_constrain_and_its_restrictions():
    # Twice the rubric's per-spend limit: "constrain", or a second "warn" which the ladder turns into constrain.
    spend(0, S["vendor"], 2 * MILLI, "README documentation by @cris-the-dev", f"{REPO}/README.md")
    r = review(0)
    assert r["decision"] in ("constrain", "warn"), r
    m = view("get_mandate", [0])
    assert m["status"] == "CONSTRAINED"
    # Restrictions: per-spend cap halved, evidence mandatory.
    a = S["agent_guard"]
    assert reverted(a.spend(args=[0, S["vendor"], MILLI + 1, "Docs by @cris-the-dev", f"{REPO}/README.md", ""]).transact())
    assert reverted(a.spend(args=[0, S["vendor"], MILLI, "Docs by @cris-the-dev", "", ""]).transact())


def test_revoke_appeal_refund():
    spend(0, S["vendor"], MILLI, "Gaming headset for the agent operator, @cris-the-dev", f"{REPO}/LICENSE")
    r = review(0)
    assert r["decision"] == "revoke", r
    assert view("get_mandate", [0])["status"] == "REVOKED"
    ok(
        S["agent_guard"]
        .appeal_revocation(args=[0, "The headset lets me focus on writing documentation, so it serves the objective."])
        .transact(wait_interval=10_000, wait_retries=60)
    )
    r = view("get_reviews", [0])[-1]
    assert r["appeal"] and r["decision"] == "revoke", r
    tx = ok(S["guard"].withdraw_remaining(args=[0]).transact())
    m = view("get_mandate", [0])
    assert m["status"] == "CLOSED"
    refund = view("get_payouts", [0])[-1]
    assert refund["kind"] == "refund" and refund["to"].lower() == S["delegator"].address.lower()
    assert refund["amount"] == 5 * MILLI - 4 * MILLI
    S["paid"].append((0, tx, refund))


def test_spend_to_a_rejecting_address():
    spend(1, S["rejecter"], MILLI, "Hosting invoice for the docs site, @cris-the-dev", f"{REPO}/README.md")
    assert view("get_mandate", [1])["budget"] == 0


def test_every_payout_settles_from_its_own_transfer():
    for mid, tx, p in S["paid"]:
        fin, block = finalization(tx)
        moved = balance(p["to"], block) - balance(p["to"], block - 1)
        failed = p["to"].lower() == S["rejecter"].lower()
        assert moved == (0 if failed else p["amount"]), (p, fin, moved)
        ok(S["guard"].settle_payout(args=[p["id"], tx, fin]).transact(wait_interval=10_000, wait_retries=60))
        got = next(x for x in view("get_payouts", [mid]) if x["id"] == p["id"])
        assert got["status"] == ("FAILED" if failed else "DELIVERED"), got
        assert got["tx"] == tx.lower()
        print(f"payout {p['id']} {p['kind']} -> {p['to']}: {got['status']}  paid {tx}  finalized {fin} (block {block}, +{moved} wei)")
        # A settled paying transaction cannot settle again.
        assert reverted(S["guard"].settle_payout(args=[p["id"], tx, fin]).transact())
    # The failed spend went back to mandate 1's budget.
    m = view("get_mandate", [1])
    assert m["budget"] == MILLI and m["spent"] == 0
