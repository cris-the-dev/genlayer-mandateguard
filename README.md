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
agent ─────── spend(to, amount, purpose, evidence URL, sha256?) ── receipt + payout ─▶ vendor
every N spends: request_review ── validators read receipts + evidence pages ──▶ decision
failed transfer? reconcile_payout ── funds back to the budget or to the delegator
```

## Live deployment

App: https://mandateguard.cristhedev.com (mandates, receipts, validator reviews and every role's actions; source in [`app/`](app/))  
Testnet Bradbury (chainId 4221): [`0x023e18d8b4feD3b62495Cb19c384ecD1E0113BeD`](https://explorer-bradbury.genlayer.com/address/0x023e18d8b4feD3b62495Cb19c384ecD1E0113BeD)

## What it does

| Layer | Mechanism | Depends on the LLM? |
|---|---|---|
| Hard limits | Escrowed budget, per-transaction cap, expiry; the agent cannot pay itself or the contract; optional delegator allowlist of recipients (`set_recipients`) | No |
| Review gating | After `review_every` spends, spending is blocked until a review runs (anyone — delegator, agent or a keeper — can trigger it) | No |
| Judgment | Validators fetch each receipt's evidence page and judge the spends against the objective and rubric | Yes, by consensus |
| Decision ladder | `continue` → full authority · `warn` → recorded, **2 warnings in a row escalate to `constrain`** · `constrain` → cap halved and evidence mandatory · `revoke` → frozen, one agent appeal, then refund · `escalate` → frozen until the delegator restores (under constraint, recorded as an override) or closes | Deterministic on top of the AI decision |
| Passive safety | `emergency_revoke` by the delegator at any time; `withdraw_remaining` after expiry | No |
| Payout ledger | Every vendor payment and refund is a payout; a transfer that provably failed is reconciled back, so nothing is lost | No |
| Cross-chain effect | Every decision emits `MandateDecision(agent, mandate_id, decision, status, permission_ref)` for an off-chain revocation controller (e.g. ERC-7710) | — |

## Supervision is retrospective

A review judges spends that have already been paid, and its decision governs
the agent's **future** authority. It does not approve a payment before it is
sent. What bounds a single payment up front is deterministic: the per-tx cap
(halved once constrained), the remaining budget, review gating (at most
`review_every` unreviewed spends), expiry, and, if the delegator sets one, the
recipient allowlist. A delegator who wants pre-approval sets
`review_every = 1` and an allowlist: then every spend goes to a known vendor
and no second spend happens before validators have judged the first.

## Consensus design

The leader returns `{decision, criteria_met, criteria_total, violations, reasoning}`.
Each validator re-fetches the evidence, re-judges, and accepts only if:

- the **decision is identical**. Every label changes state differently (a
  `warn` counts toward the two-warnings-to-constrain rule, `continue` resets
  it), so there is no "close enough" class. A colluding leader cannot whitewash
  a bad agent and a griefing leader cannot revoke a good one;
- the number of rubric criteria met differs by at most 1, and `criteria_total` matches;
- the payload is well-formed and bounded (reasoning ≤ 400 chars, ≤ 5 violations);
- for every receipt with an evidence commitment, the leader saw the same
  evidence status (`match` / `changed` / `unavailable`) as the validator.

Errors follow the official classes: reproducible `[TRANSIENT]` failures are
agreed (the tx reverts, the review can be retried); `[LLM_ERROR]` (e.g. an
unknown decision label) is always rejected so a new leader is chosen. Dead
evidence links become `[UNAVAILABLE]` instead of blocking the review — a
missing invoice is itself evidence.

## Evidence integrity

Evidence URLs are mutable, so `spend` takes an optional `evidence_sha256`: the
SHA-256 of the page text the agent is relying on. At review time each
validator hashes what it fetches:

- `match`: the prompt marks the page as verified, identical to spend time;
- `changed`: the prompt flags it as edited after the spend (weak evidence);
- `unavailable`: no evidence for that spend.

Because the status is deterministic for committed receipts, validators reject a
leader that reports a different one. Every review stores, per receipt, the
status, the SHA-256 of the text judged and its full length
(`get_reviews(...).evidence`), so anyone can later check what was read.

Pages longer than 3,000 characters are cut, never silently: the prompt says
`[TRUNCATED: first 3000 of N characters shown]` and instructs the model to
`escalate` if the missing part could decide the outcome.

## Payments, refunds and reconciliation

Value transfers from a GenLayer contract are emitted messages that settle after
the transaction finalizes; a recipient contract can still reject one. So the
contract never assumes a payment arrived:

- `spend` and every refund (`emergency_revoke`, `withdraw_remaining`,
  `resolve_escalation(id, false)`) first check the contract holds the amount,
  then record a **payout** (`get_payouts`) and keep `expected_balance`, the
  sum the contract should hold after all sent payouts.
- If a transfer failed, the contract's real balance exceeds
  `expected_balance` (`get_accounting().unaccounted`). After a 1-day settle
  window the delegator or agent calls `reconcile_payout(payout_id)`. A failed
  vendor payment returns to the mandate's budget (and `spent` is reduced); the
  receipt stays, marked `FAILED`. A failed refund, or a payment that fails
  after the mandate closed, is credited to the delegator's `recoverable`
  balance, which `recover(id, to)` sends to any address the delegator picks.
- A payout can only be reconciled once, and only against unaccounted funds,
  so one bounce cannot be claimed twice and a delivered transfer cannot be
  reversed.

## Escalation override

When validators `escalate`, only the delegator can unfreeze the mandate.
`resolve_escalation(id, true)` does **not** clear the concern: the agent
resumes as `CONSTRAINED` (half cap, evidence required), and an entry with
`decision = "override"` and `source = "delegator"` is added to the review log,
stating it is not a validator decision. It does not count toward the agent's
`reviews_passed`. The escalated spends stay on record.

Prompt injection: purposes (agent-written) and evidence pages (web) are fenced
in `<<< >>>` with delimiter neutralisation; the model only picks a decision
label — amounts, recipients and refunds are enforced by contract state.

## API

| Method | Who | Notes |
|---|---|---|
| `grant(agent, objective, rubric_json, max_per_tx, review_every, duration_seconds, permission_ref)` payable | delegator | escrow = `msg.value`; review_every 1–10 |
| `top_up(id)` payable | delegator | |
| `set_recipients(id, recipients_json)` | delegator | allowlist of vendor addresses; `[]` = any; the agent is never allowed |
| `spend(id, to, amount, purpose, evidence_url, evidence_sha256)` | agent | receipt + payout; blocked when frozen, expired, over cap, review due, recipient not allowed, or the contract cannot pay; sha256 optional |
| `request_review(id)` | anyone | consensus review of the spends since the last review |
| `appeal_revocation(id, statement)` | agent | once, within 2 days of a revoke; re-judges the same spends |
| `resolve_escalation(id, restore)` | delegator | restore under constraint (recorded override) or close and refund |
| `emergency_revoke(id)` | delegator | immediate close + refund |
| `withdraw_remaining(id)` | delegator | after expiry, or after a revoke once the appeal is used/expired |
| `reconcile_payout(payout_id)` | delegator or agent | after the settle window, if the contract still holds the funds |
| `recover(id, to)` | delegator | send the recoverable balance (failed refunds) to any address |
| `get_mandate`, `get_receipts`, `get_payouts`, `get_reviews`, `get_accounting`, `get_agent_record`, `get_mandate_count` | view | |

`examples/agent_supervisor.ts` shows an agent loop with genlayer-js and maps
the latest review to the Internet Court `AgentReviewDecision` payload.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
genvm-lint check contracts/mandate_guard.py
pytest tests/direct -v                         # 52 tests
# integration, on Bradbury, against the packed code (keys in GL_PK0..2 env vars)
python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
cd tests/integration && gltest . -v -s --network testnet_bradbury
```

### Deploying to Testnet Bradbury

The source is 35.7 KB; Bradbury rejects deploys above ~20 KB of code. Deploy
the output of `deploy/shrink.py` (AST-checked; 8.9 KB packed). CI re-runs all
52 direct tests against the packed code.

```bash
python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
genlayer network && genlayer deploy --contract build/mandate_guard.py
```

## Tests (52 direct)

- **Mandate lifecycle** — grant validation; spend receipts, transfers and events; hard limits independent of the LLM; review gating and keeper-triggered reviews; warn→warn escalation to constrain; constrained half-cap + mandatory evidence and recovery; revoke → appeal window → refund; successful appeal restores authority and reputation; failed appeal is final and not double counted; escalation restored or closed by the delegator; emergency revoke; expiry; top-up; decision events carry `permission_ref` with correctly bound indexed fields.
- **Consensus (validator replay)** — agrees with honest variation; rejects any different decision (including continue vs warn), criteria disagreement, a whitewashing leader, a griefing revoke, malformed/oversized payloads, fake transient errors and LLM errors; unknown labels revert; agent text and evidence are fenced; dead links don't block reviews.
- **Adversarial** (`test_safety.py`) — a delivered payment cannot be reconciled; a failed one returns to the budget once, after the settle window, by a party only; one bounce cannot be claimed twice; spends revert when the contract cannot pay; failed refunds after emergency revoke, expiry withdraw and escalation close become recoverable and can be recovered once; double close is rejected; unauthorized and self-dealing spends; recipient allowlist; evidence commitment match, edited evidence binding validators, changed/unavailable statuses, explicit truncation; repeated escalation overrides never count as clearance; conflicting leader decisions are rejected.

## License

MIT
