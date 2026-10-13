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
Testnet Bradbury (chainId 4221): [`0x637301a7Bc5F8b0b0E8bd6AC858894Ac94761BD3`](https://explorer-bradbury.genlayer.com/address/0x637301a7Bc5F8b0b0E8bd6AC858894Ac94761BD3)

## Bradbury evidence

Contract `0x637301a7Bc5F8b0b0E8bd6AC858894Ac94761BD3` (deploy [`0x4db6966e…`](https://explorer-bradbury.genlayer.com/tx/0x4db6966e30c6d84cccf10dc8c72fb2440089c59a24478f66a5b3433eb59eff38)), on-chain code identical to `build/mandate_guard.py` (sha256 `b12fc8a6…`). Driver: one transaction per step, delegator, agent and vendor are separate accounts.

| Mandate | Step | Transaction | Outcome |
|---|---|---|---|
| #0 | grant 0.004 GEN, cap 0.002, review every 2 | [`0xf97812e9…`](https://explorer-bradbury.genlayer.com/tx/0xf97812e9003307e8ec1207239d6367f492f6b87b286d7ec0df98c6e4bda95174) | accepted |
| #0 | recipient allowlist | [`0xa45a8d73…`](https://explorer-bradbury.genlayer.com/tx/0xa45a8d739cb8c922cbadec345ddd42cabef9abb5b1e41b2c2deb191d5df99915) | accepted |
| #0 | top up 0.001 GEN | [`0xc9ad693f…`](https://explorer-bradbury.genlayer.com/tx/0xc9ad693f25b8b0501e5d805b67555f26d10fe37068a52407139359998e7ccb1c) | accepted |
| #0 | spend, evidence committed (sha256) | [`0xf1e8055c…`](https://explorer-bradbury.genlayer.com/tx/0xf1e8055c0169976fd254f502f587fa24389a2564a7fef8ddd9531e1d8f8ec608) | accepted |
| #0 | spend, LICENSE as evidence | [`0x141afa7e…`](https://explorer-bradbury.genlayer.com/tx/0x141afa7ebe415d985df44af757f095058f554bec880fb242c468e0af039fc354) | accepted |
| #0 | review | [`0xa08b1059…`](https://explorer-bradbury.genlayer.com/tx/0xa08b1059032194465916817e75e17b391ff5355510c20c85d9d87a191be62eb7) | UNDETERMINED: leader said warn (LICENSE is not docs/examples/tests), validators split; state unchanged |
| #0 | withdraw after expiry | [`0x6c615fe1…`](https://explorer-bradbury.genlayer.com/tx/0x6c615fe12a758ca073b4e40712df2b147f43711d0b3c3b48ae8f7e7e36a084f9) | finalized: CLOSED, refund payout SENT |
| #1 | grant, review every spend | [`0x9d0b8382…`](https://explorer-bradbury.genlayer.com/tx/0x9d0b8382e6fbc619613cc8d885aa504c6a295d21aedd9bc28399133d23d0d546) | finalized |
| #1 | spend for tests/direct/test_safety.py, sha committed | [`0xd29e8a5e…`](https://explorer-bradbury.genlayer.com/tx/0xd29e8a5e541554d081021355c6f7022d1db1c32105df7a2eed037a3adcf3f132) | accepted |
| #1 | review | [`0xbc429f50…`](https://explorer-bradbury.genlayer.com/tx/0xbc429f50f99796f40cd06f6392d5283e2de5694e8e47f91fd6475e662ca7d2f9) | accepted: **continue**, 3/3 criteria, evidence **match** |
| #1 | spend for README | [`0xf973eb0d…`](https://explorer-bradbury.genlayer.com/tx/0xf973eb0dcb947d01ef632a7747bdaedfefb590d1e574fa81d93900e6ca3d84f8) | accepted |
| #1 | review | [`0x2165a841…`](https://explorer-bradbury.genlayer.com/tx/0x2165a84157b7a22f239a5754ad2dc3671afdb3e4fb4a1e73986b515635f8ff7e) | accepted: **continue**, 4 of 5 agree |
| #2 | grant | [`0xe6a3d69c…`](https://explorer-bradbury.genlayer.com/tx/0xe6a3d69ccce359c4da41c3d498857a6295b6dd06d2fed7426da6fa0e681d2073) | accepted |
| #2 | spend 0.002 GEN (over the rubric's 0.001 limit) | [`0x84294559…`](https://explorer-bradbury.genlayer.com/tx/0x842945592e16201482b2e764dcb7abe32c274f6c3db1fc6a137f5d281a5b246b) | accepted |
| #2 | review | [`0xd6b68b80…`](https://explorer-bradbury.genlayer.com/tx/0xd6b68b808ddcf812caed3fafd137ee24a386a02f03ea99bae5838419a13bff66) | finalized: **constrain** (spend is twice the rubric limit), per-spend cap halved to 0.001 GEN; two earlier attempts hit LEADER_TIMEOUT and changed nothing |
| #2 | emergency revoke | [`0x28b4c2f8…`](https://explorer-bradbury.genlayer.com/tx/0x28b4c2f86131e2ddc77b5206af1f0f371b95c41c3b1e19a26e3d328c4c1b979f) | accepted: CLOSED, remaining budget refunded |
| #3 | grant | [`0xb3448fae…`](https://explorer-bradbury.genlayer.com/tx/0xb3448faead4eabc0128012eda1e03c06cb3ca48d12a1229c78241aa1581be446) | accepted |
| #3 | spend on a gaming headset | [`0xa3c72323…`](https://explorer-bradbury.genlayer.com/tx/0xa3c72323418e071f99eb5e5c28c8e8135ddf50c1f5e80af5f202a8b436385e4b) | accepted |
| #3 | review | [`0xdbad092a…`](https://explorer-bradbury.genlayer.com/tx/0xdbad092a2d9f79735937e2d6308ba51a6403cef18e91d1b4b9bab4a45c4f44b4) | finalized: **revoke**, 1/3 criteria (headset out of scope, LICENSE shows no paid work) |
| #3 | agent appeal | [`0x88bd387d…`](https://explorer-bradbury.genlayer.com/tx/0x88bd387dcfa5c2f52ecd7c43eff0f55c24a47611e766a863b16c778710c4dea2) | finalized: re-review upholds **revoke** |
| #3 | withdraw | [`0xe042450f…`](https://explorer-bradbury.genlayer.com/tx/0xe042450f3af555cad35a50d77d7198215848c8d5602b8aaceb6009b72fd6833a) | accepted: CLOSED, remaining budget refunded |
| #4 | grant | [`0x3d45cfed…`](https://explorer-bradbury.genlayer.com/tx/0x3d45cfed95a7870f74d0284f33c43f56d0338106e320da7237abfa415980e265) | accepted |
| #4 | spend, evidence URL returns 404 | [`0x78c19a9b…`](https://explorer-bradbury.genlayer.com/tx/0x78c19a9b7a43e9ffffdd7bc61f046252aa351da9eb0a434e6129c33c78c6ac4f) | finalized |
| #4 | review | [`0x14efb00b…`](https://explorer-bradbury.genlayer.com/tx/0x14efb00be1e1fcbfba7de517b07b3dc7f78ce2048796cd0a5279a3376e976e02) | accepted: **escalate**, evidence `unavailable` |
| #4 | delegator restores | [`0x8f13aa4b…`](https://explorer-bradbury.genlayer.com/tx/0x8f13aa4b4794430c22f524cdffc7789e252e1c09682fab89cade5076fdf69ce2) | accepted: review recorded as `override` by `delegator`, mandate CONSTRAINED |
| #4 | emergency revoke | [`0x9009d569…`](https://explorer-bradbury.genlayer.com/tx/0x9009d569bb676f25ec1cec95424eee0481ab1e9c049478ad763c1a480312ccfc) | finalized: CLOSED, remaining budget refunded |

After the run `get_accounting` reports `unaccounted: 0`: every payout and refund reached its recipient. Mandate #1 is left ACTIVE.

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
SHA-256 of the HTTP response body the agent is relying on (`curl -s URL |
sha256sum`). Evidence is fetched with a plain GET, not a browser render, so the
hash is reproducible. At review time each validator hashes what it fetches:

- `match`: the prompt marks the page as verified, identical to spend time;
- `changed`: the prompt flags it as edited after the spend (weak evidence);
- `unavailable`: fetch failed or HTTP status >= 400; no evidence for that spend.

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
pytest tests/direct -v                         # 53 tests
# integration, on Bradbury, against the packed code (keys in GL_PK0..2 env vars)
python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
cd tests/integration && gltest . -v -s --network testnet_bradbury
```

### Deploying to Testnet Bradbury

The source is 36.2 KB; Bradbury rejects deploys above ~20 KB of code. Deploy
the output of `deploy/shrink.py` (AST-checked; 9.0 KB packed). CI re-runs all
53 direct tests against the packed code.

```bash
python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
genlayer network && genlayer deploy --contract build/mandate_guard.py
```

## Tests (53 direct)

- **Mandate lifecycle** — grant validation; spend receipts, transfers and events; hard limits independent of the LLM; review gating and keeper-triggered reviews; warn→warn escalation to constrain; constrained half-cap + mandatory evidence and recovery; revoke → appeal window → refund; successful appeal restores authority and reputation; failed appeal is final and not double counted; escalation restored or closed by the delegator; emergency revoke; expiry; top-up; decision events carry `permission_ref` with correctly bound indexed fields.
- **Consensus (validator replay)** — agrees with honest variation; rejects any different decision (including continue vs warn), criteria disagreement, a whitewashing leader, a griefing revoke, malformed/oversized payloads, fake transient errors and LLM errors; unknown labels revert; agent text and evidence are fenced; dead links don't block reviews.
- **Adversarial** (`test_safety.py`) — a delivered payment cannot be reconciled; a failed one returns to the budget once, after the settle window, by a party only; one bounce cannot be claimed twice; spends revert when the contract cannot pay; failed refunds after emergency revoke, expiry withdraw and escalation close become recoverable and can be recovered once; double close is rejected; unauthorized and self-dealing spends; recipient allowlist; evidence commitment match, edited evidence binding validators, changed/unavailable statuses, explicit truncation; repeated escalation overrides never count as clearance; conflicting leader decisions are rejected.

## License

MIT
