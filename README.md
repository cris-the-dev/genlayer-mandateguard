# MandateGuard — consensus supervision for autonomous agents' spending authority

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

AI agents are starting to hold budgets: buy compute, pay APIs, hire other
agents. Spending limits stop an agent from spending *too much*; nothing stops
it from spending on the *wrong things*. **MandateGuard** is a standalone
Intelligent Contract that supervises an agent's mandate the way a careful
manager would — and the manager is GenLayer consensus, not one person.

It implements the **agent supervisor** pattern of the
[Internet Court](https://github.com/internet-court/internet-court-skill)
specification (`continue / warn / constrain / revoke / escalate`) as working
on-chain code.

```
delegator ── grant(budget, objective, rubric, per-tx cap, review cadence, expiry) ──▶ MandateGuard
agent ─────── spend(to, amount, purpose, evidence URL) ── receipt + transfer ───────▶ vendor
every N spends: request_review ── validators read receipts + evidence pages ──▶ decision
```

## Live deployment

App: https://mandateguard.cristhedev.com (mandates, receipts, validator reviews and every role's actions; source in [`app/`](app/))  
Testnet Bradbury (chainId 4221): [`0x023e18d8b4feD3b62495Cb19c384ecD1E0113BeD`](https://explorer-bradbury.genlayer.com/address/0x023e18d8b4feD3b62495Cb19c384ecD1E0113BeD)

## What it does

| Layer | Mechanism | Depends on the LLM? |
|---|---|---|
| Hard limits | Escrowed budget, per-transaction cap, expiry | No |
| Review gating | After `review_every` spends, spending is blocked until a review runs (anyone — delegator, agent or a keeper — can trigger it) | No |
| Judgment | Validators fetch each receipt's evidence page and judge the spends against the objective and rubric | Yes, by consensus |
| Decision ladder | `continue` → full authority · `warn` → recorded, **2 warnings in a row escalate to `constrain`** · `constrain` → cap halved and evidence mandatory · `revoke` → frozen, one agent appeal, then refund · `escalate` → frozen until the delegator restores or closes | Deterministic on top of the AI decision |
| Passive safety | `emergency_revoke` by the delegator at any time; `withdraw_remaining` after expiry | No |
| Cross-chain effect | Every decision emits `MandateDecision(agent, mandate_id, decision, status, permission_ref)` for an off-chain revocation controller (e.g. ERC-7710) | — |

## Consensus design

The leader returns `{decision, criteria_met, criteria_total, violations, reasoning}`.
Each validator re-fetches the evidence, re-judges, and accepts only if:

- the **restrictiveness class** matches — `continue`/`warn` are one *permissive*
  class; `constrain`, `revoke` and `escalate` are each their own class. So a
  colluding leader cannot whitewash a bad agent, and a griefing leader cannot
  revoke a good one;
- the number of rubric criteria met differs by at most 1, and `criteria_total` matches;
- the payload is well-formed and bounded (reasoning ≤ 400 chars, ≤ 5 violations).

Errors follow the official classes: reproducible `[TRANSIENT]` failures are
agreed (the tx reverts, the review can be retried); `[LLM_ERROR]` (e.g. an
unknown decision label) is always rejected so a new leader is chosen. Dead
evidence links become `[UNAVAILABLE]` instead of blocking the review — a
missing invoice is itself evidence.

Prompt injection: purposes (agent-written) and evidence pages (web) are fenced
in `<<< >>>` with delimiter neutralisation; the model only picks a decision
label — amounts, recipients and refunds are enforced by contract state.

## API

| Method | Who | Notes |
|---|---|---|
| `grant(agent, objective, rubric_json, max_per_tx, review_every, duration_seconds, permission_ref)` payable | delegator | escrow = `msg.value`; review_every 1–10 |
| `top_up(id)` payable | delegator | |
| `spend(id, to, amount, purpose, evidence_url)` | agent | receipt + transfer; blocked when frozen, expired, over cap or review due |
| `request_review(id)` | anyone | consensus review of the spends since the last review |
| `appeal_revocation(id, statement)` | agent | once, within 2 days of a revoke; re-judges the same spends |
| `resolve_escalation(id, restore)` | delegator | restore authority or close and refund |
| `emergency_revoke(id)` | delegator | immediate close + refund |
| `withdraw_remaining(id)` | delegator | after expiry, or after a revoke once the appeal is used/expired |
| `get_mandate`, `get_receipts`, `get_reviews`, `get_agent_record`, `get_mandate_count` | view | |

`examples/agent_supervisor.ts` shows an agent loop with genlayer-js and maps
the latest review to the Internet Court `AgentReviewDecision` payload.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
genvm-lint check contracts/mandate_guard.py
pytest tests/direct -v                         # 35 tests
gltest tests/integration -v -s --network studionet
```

### Deploying to Testnet Bradbury

The source is 24.8 KB; Bradbury rejects deploys above ~20 KB of code. Deploy
the output of `deploy/shrink.py` (AST-checked; 17.6 KB stripped, 6.6 KB
packed). CI re-runs all 35 direct tests against the packed code.

```bash
python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
genlayer network && genlayer deploy --contract build/mandate_guard.py
```

## Tests (35 direct)

- **Mandate lifecycle** — grant validation; spend receipts, transfers and events; hard limits independent of the LLM; review gating and keeper-triggered reviews; warn→warn escalation to constrain; constrained half-cap + mandatory evidence and recovery; revoke → appeal window → refund; successful appeal restores authority and reputation; failed appeal is final and not double counted; escalation restored or closed by the delegator; emergency revoke; expiry; top-up; decision events carry `permission_ref` with correctly bound indexed fields.
- **Consensus (validator replay)** — agrees with honest variation and continue≈warn; rejects every class change, criteria disagreement, a whitewashing leader, a griefing revoke, malformed/oversized payloads, fake transient errors and LLM errors; unknown labels revert; agent text and evidence are fenced; dead links don't block reviews.

## License

MIT
