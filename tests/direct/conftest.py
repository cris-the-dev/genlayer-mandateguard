"""Fixtures for MandateGuard direct-mode tests."""

import json

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
    direct_vm.mock_web(r"evidence\.example\.com", {"status": 200, "body": "Invoice: 4x A100 hours, $120"})
    return c


def spend(vm, guard, agent, amount=GEN, purpose="Rent GPU hours for training", url="https://evidence.example.com/inv/1"):
    vm.sender = agent
    return guard.spend(0, VENDOR, amount, purpose, url)


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
