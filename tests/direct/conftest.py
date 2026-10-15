"""Fixtures for MandateGuard direct-mode tests."""

import json
from datetime import datetime, timedelta

import pytest

GEN = 10**18
BUDGET = 10 * GEN
CAP = 2 * GEN
DAY = 86_400
OBJECTIVE = "Buy compute and datasets needed to train a small sentiment model for Vietnamese reviews."
RUBRIC = json.dumps(
    [
        "Each spend serves the objective",
        "Amounts are proportional to the stated purpose",
        "Each spend has verifiable evidence",
    ]
)
VENDOR = "0x" + "5e" * 20


def to_hex(addr) -> str:
    if hasattr(addr, "as_hex"):
        return addr.as_hex
    from genlayer.py.types import Address

    return Address(addr).as_hex


class Ledger:
    def __init__(self):
        self.transfers = []
        self.events = []

    def paid_to(self, addr) -> int:
        h = (addr if isinstance(addr, str) else to_hex(addr)).lower()
        return sum(v for a, v in self.transfers if a.lower() == h)

    def decisions(self):
        return [e["decision"] for e in self.events if "decision" in e]


@pytest.fixture
def ledger():
    import gltest.direct.wasi_mock as wm

    book = Ledger()
    original = wm._handle_gl_call

    def spy(vm, request):
        if isinstance(request, dict):
            if "EthSend" in request:
                r = request["EthSend"]
                book.transfers.append((to_hex(r["address"]), int(r["value"])))
            if "EmitEvent" in request:
                book.events.append(request["EmitEvent"]["blob"])
        return original(vm, request)

    wm._handle_gl_call = spy
    yield book
    wm._handle_gl_call = original


@pytest.fixture
def guard(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Mandate 0: Alice (delegator) -> Bob (agent), review every 2 spends."""
    direct_vm.warp("2030-01-01T00:00:00Z")
    c = direct_deploy("contracts/mandate_guard.py")
    direct_vm.sender = direct_alice
    direct_vm.value = BUDGET
    c.grant(to_hex(direct_bob), OBJECTIVE, RUBRIC, CAP, 2, 30 * DAY, "erc7710:0xabc")
    direct_vm.value = 0
    chain_balance(direct_vm, BUDGET)
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": "Invoice: 4x A100 hours, $120"})
    return c


def chain_balance(vm, amount):
    """The mock never moves value, so tests set the contract's balance as the chain would show it."""
    vm.deal(vm._contract_address, amount)


def tick(vm, seconds=1):
    """Advance block time; the contract allows one payment per sender per second."""
    t = datetime.fromisoformat(vm._datetime.replace("Z", "+00:00")) + timedelta(seconds=seconds)
    vm.warp(t.strftime("%Y-%m-%dT%H:%M:%SZ"))


def spend(
    vm, guard, agent, amount=GEN, purpose="Rent GPU hours for training", url="https://evidence.example.com/inv/1", sha="", to=VENDOR
):
    tick(vm)
    vm.sender = agent
    return guard.spend(0, to, amount, purpose, url, sha)


# ── Fake Bradbury RPC for settle_payout ─────────────────────────────────────

CONSENSUS_MAIN = "0x0112bf6e83497965a5fdd6dad1e447a6e004271d"
MESSAGES = "0x27872802226532fcd7fea2f00addbffbd3380ade"
T_FINALIZED = "0x24196ec40f90671b7144e716978686b4f3c7d6b00b23da3971ef2b52af27d87f"
T_EXECUTED = "0x4aacc1769103d0575734a31601a30d8f74c7843414f868342af438b4fdc4d78e"
T_MESSAGE = "0x1a2b93b175bf31d44b127b5c4c0f72cbf128f5230ad594a52a00dfa559c96b51"


def _rlp(item) -> bytes:
    def prefix(n, off):
        if n < 56:
            return bytes([off + n])
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return bytes([off + 55 + len(b)]) + b

    if isinstance(item, list):
        body = b"".join(_rlp(x) for x in item)
        return prefix(len(body), 0xC0) + body
    return item if len(item) == 1 and item[0] < 0x80 else prefix(len(item), 0x80) + item


def _pad(addr: str) -> str:
    return "0x" + addr.lower()[2:].rjust(64, "0")


class Chain:
    """Serves gen_getTransactionReceipt / eth_getTransactionReceipt like Bradbury,
    for paying transactions registered with `pay`."""

    def __init__(self, vm):
        self.vm = vm
        self.receipts = {}  # (rpc method, hash) -> result
        self.n = 0
        self.down = False

    def _hash(self):
        self.n += 1
        return "0x" + f"{self.n:064x}"

    def pay(self, guard, payout_id, method, args, delivered=True, status=7, result=1, sender=None, at=None, contract=None):
        """Record the paying transaction of `payout_id` and its finalization. Returns (tx, finalize_tx)."""
        from genlayer.py import calldata

        p = next(x for m in range(guard.get_mandate_count()) for x in guard.get_payouts(m) if x["id"] == payout_id)
        me = (contract or to_hex(self.vm._contract_address)).lower()
        tx, fin = self._hash(), self._hash()
        self.receipts[("gen_getTransactionReceipt", tx)] = {
            "sender": (sender or p["sender"]).lower(),
            "recipient": me,
            "status": status,
            "txExecutionResult": result,
            "timestamps": {"Created": p["at"] if at is None else at},
            "txCallData": _rlp([calldata.encode({"method": method, "args": args}), b"\x00"]).hex(),
        }
        msg = "0x" + f"{self.n:064x}"
        logs = [
            {"address": CONSENSUS_MAIN, "topics": [T_FINALIZED, tx], "data": "0x"},
            {"address": MESSAGES, "topics": [T_MESSAGE, tx, msg], "data": "0x"},
        ]
        if delivered:
            logs.append({"address": me, "topics": [T_EXECUTED, _pad(p["to"])], "data": msg + "00" * 64})
        self.receipts[("eth_getTransactionReceipt", fin)] = {"status": "0x1", "to": CONSENSUS_MAIN, "logs": logs}
        return tx, fin

    def answer(self, data):
        body = data.get("body") or b""
        req = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
        if self.down:
            return {"ok": {"response": {"status": 502, "headers": {}, "body": b"bad gateway"}}}
        params = req["params"][0]
        key = params["txId"] if isinstance(params, dict) else params
        out = {"jsonrpc": "2.0", "id": req["id"], "result": self.receipts.get((req["method"], key))}
        return {"ok": {"response": {"status": 200, "headers": {}, "body": json.dumps(out).encode()}}}


@pytest.fixture
def chain(direct_vm):
    import gltest.direct.wasi_mock as wm

    c = Chain(direct_vm)
    original = wm._handle_web_request

    def route(vm, data):
        if "rpc-bradbury" in data.get("url", ""):
            return c.answer(data)
        return original(vm, data)

    wm._handle_web_request = route
    yield c
    wm._handle_web_request = original


def verdict(vm, decision, met=3, pattern=r"supervise an autonomous AI agent"):
    vm.mock_llm(
        pattern,
        json.dumps(
            {
                "decision": decision,
                "criteria": [{"criterion": i + 1, "met": i < met} for i in range(3)],
                "violations": [] if decision in ("continue", "warn") else ["off-objective spend"],
                "reasoning": f"Decision: {decision}.",
            }
        ),
    )
