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
after finalization: settle_payout ── validators read that transfer's result; failed → budget or delegator
```

## Live deployment

App: https://mandateguard.cristhedev.com (mandates, receipts, validator reviews and every role's actions; source in [`app/`](app/))  
Testnet Bradbury (chainId 4221): [`0xa66bfADc1F2A49de8465577dd55ba5E1ED7d9256`](https://explorer-bradbury.genlayer.com/address/0xa66bfADc1F2A49de8465577dd55ba5E1ED7d9256)

## Bradbury evidence

Run by [`tests/integration/test_mandate_guard.py`](tests/integration/test_mandate_guard.py) (6 passed, 41 min). Contract `0xa66bfADc1F2A49de8465577dd55ba5E1ED7d9256` (deploy [`0x6ddfd322…`](https://explorer-bradbury.genlayer.com/tx/0x6ddfd32237d51cbcd0dc95da96e7d29de485a27aaf6eb33707fb5e13c9052e9d)), code `build/mandate_guard.py` (sha256 `a9ef69a0…`). Delegator, agent and vendor are separate accounts.

| Mandate | Step | Transaction | Outcome |
|---|---|---|---|
| #0 | grant 0.005 GEN, cap 0.002, review every spend | [`0xf1a5307b…`](https://explorer-bradbury.genlayer.com/tx/0xf1a5307b04073b5112bca6e31f1fb53dfaadb35a70e1fcf6112c34952d0e92cf) | finalized |
| #1 | grant 0.001 GEN | [`0x355cd7ad…`](https://explorer-bradbury.genlayer.com/tx/0x355cd7ad941c453144bdbd6fff8679ab3e7bea2e2d0c9160311e865193527b96) | finalized |
| #0 | spend 0.001, purpose names no contributor | [`0x36b8abff…`](https://explorer-bradbury.genlayer.com/tx/0x36b8abff433808d4708175a00dbdb3d509ebb8cd6490f3e346ca5123bf951bcc) | payout 0 SENT |
| #0 | review | [`0x2ca21e89…`](https://explorer-bradbury.genlayer.com/tx/0x2ca21e8949d0f40f19b637ef3589967d69b1f7a09f73dfb13455f14bd70dee00) | **warn**, 2/3 criteria (no GitHub handle): WARNED |
| #0 | spend 0.002 (twice the rubric limit) | [`0x255f6fe9…`](https://explorer-bradbury.genlayer.com/tx/0x255f6fe9dd156f308ffda36be6dfbc7516b52ca5be3ddba04ad3a5603acc9f7e) | payout 1 SENT |
| #0 | review | [`0xe02883f8…`](https://explorer-bradbury.genlayer.com/tx/0xe02883f8c4674849ee8500f315b2696de79a1ef2b81fa76e91e38b0b2ab4d001) | **constrain**: CONSTRAINED, cap halved, evidence mandatory |
| #0 | spend 0.001 + 1 wei | [`0x026bb6d2…`](https://explorer-bradbury.genlayer.com/tx/0x026bb6d22021fb22e85231696e724d530365cae339e39895964843c231514a75) | rejected: over the halved cap |
| #0 | spend without evidence URL | [`0xf724e70a…`](https://explorer-bradbury.genlayer.com/tx/0xf724e70aa25c9cb52586814d3a82c4eb72423690f71d0769e322c229fbf7c077) | rejected: evidence mandatory |
| #0 | spend on a gaming headset | [`0x445affaf…`](https://explorer-bradbury.genlayer.com/tx/0x445affaf3a8c97eb685d7a90b5fa48d6613cdccff284515d2f360d822a4f9ee3) | payout 2 SENT |
| #0 | review | [`0xc0068453…`](https://explorer-bradbury.genlayer.com/tx/0xc0068453bb01dc3b51e9a4fdbc0c488e1c83ef0309b7f6912b08a381d6ea1e0a) | **revoke** (headset out of scope): REVOKED |
| #0 | agent appeal | [`0xc6eb5646…`](https://explorer-bradbury.genlayer.com/tx/0xc6eb56466c789d31b95ed4f5ec2c6e55f2955f58e5e0d56ea075151c7933d093) | re-review upholds **revoke** |
| #0 | withdraw | [`0xe367886a…`](https://explorer-bradbury.genlayer.com/tx/0xe367886a2fad25993ba29c73618e31642d3a920d4ee0ce487a5eafffb8e5c3dc) | CLOSED, refund payout 3 (0.001) SENT |
| #1 | spend 0.001 to an EVM contract that rejects value | [`0x2bd93180…`](https://explorer-bradbury.genlayer.com/tx/0x2bd931809390512088a4ab1c1a5df57819c08d6997bc1320395b89372b6c9cb2) | payout 4 SENT, budget 0 |

Each payout settled from its own transfer, after the paying transaction finalized. Balance change is the recipient's `eth_getBalance` at the finalizing block minus the block before, checked by the test:

| Payout | Kind | Paid by | Finalized by (block) | Recipient balance | `settle_payout` | Result |
|---|---|---|---|---|---|---|
| 0 | spend → vendor | [`0x36b8abff…`](https://explorer-bradbury.genlayer.com/tx/0x36b8abff433808d4708175a00dbdb3d509ebb8cd6490f3e346ca5123bf951bcc) | [`0x55206a6f…`](https://explorer-bradbury.genlayer.com/tx/0x55206a6f28ccf0ca499c8a47b8de14a3a61719877db15cb34e00b3040774bb8e) (25245291) | +0.001 GEN | [`0x9e562af7…`](https://explorer-bradbury.genlayer.com/tx/0x9e562af7915e6e7f8d22083b4b0bf8bdb9237f8c573f26137237f24ca7a19c42) | DELIVERED |
| 1 | spend → vendor | [`0x255f6fe9…`](https://explorer-bradbury.genlayer.com/tx/0x255f6fe9dd156f308ffda36be6dfbc7516b52ca5be3ddba04ad3a5603acc9f7e) | [`0xd3c375f9…`](https://explorer-bradbury.genlayer.com/tx/0xd3c375f958e47390a8bcd42812052eb4cbc4966b8a3fbe1a1a1b365cbad11c6a) (25245405) | +0.002 GEN | [`0xf0f9b74a…`](https://explorer-bradbury.genlayer.com/tx/0xf0f9b74afce9da44f7efd9634bbcc13a55e9ba27149773697ff231e054cc5507) | DELIVERED |
| 2 | spend → vendor | [`0x445affaf…`](https://explorer-bradbury.genlayer.com/tx/0x445affaf3a8c97eb685d7a90b5fa48d6613cdccff284515d2f360d822a4f9ee3) | [`0x36aa5d25…`](https://explorer-bradbury.genlayer.com/tx/0x36aa5d255e4cbe3d3816824791d1712c56d7c5dbb0f92ba495f0a1d9b10d2123) (25245655) | +0.001 GEN | [`0x895e7f20…`](https://explorer-bradbury.genlayer.com/tx/0x895e7f200f598717336a0cba401def5cf769053196ade3bcc254909ad7c0ea71) | DELIVERED |
| 3 | refund → delegator | [`0xe367886a…`](https://explorer-bradbury.genlayer.com/tx/0xe367886a2fad25993ba29c73618e31642d3a920d4ee0ce487a5eafffb8e5c3dc) | [`0x218ad947…`](https://explorer-bradbury.genlayer.com/tx/0x218ad947043dc38dc306fe9f6bb638d37d7f2a1e290a0d6f0c9b8d7c859c0da4) (25245802) | +0.001 GEN | [`0x58291200…`](https://explorer-bradbury.genlayer.com/tx/0x582912000a4e8c1a80a365faa9ff9dbd4e4634fe92004bc200d79628129b90c8) | DELIVERED |
| 4 | spend → rejecter | [`0x2bd93180…`](https://explorer-bradbury.genlayer.com/tx/0x2bd931809390512088a4ab1c1a5df57819c08d6997bc1320395b89372b6c9cb2) | [`0x41c9add0…`](https://explorer-bradbury.genlayer.com/tx/0x41c9add052ece7d0a931788776f42ad5c469530e0c788d67bf2c64774afb2b62) (25245847) | 0 GEN | [`0x4586349e…`](https://explorer-bradbury.genlayer.com/tx/0x4586349e89250ed372a71c38c978305b060ad6b1776cad2645215fd113343d07) | FAILED: 0.001 back to mandate #1's budget |

Settling the same payout again is rejected each time ([`0x588fee72…`](https://explorer-bradbury.genlayer.com/tx/0x588fee724436052ca0b1f9a5c9a1419736c51d01b0c611aadb56e7d90ca924e3), [`0xf5430e8c…`](https://explorer-bradbury.genlayer.com/tx/0xf5430e8cfc84f79680ecff5bd19572065c04494db090c96ce7d5e93e03d653dd), [`0xa9c33e14…`](https://explorer-bradbury.genlayer.com/tx/0xa9c33e1492f465ffd890ebfd836ab232b0301a18d8734c8794f7e1d8236c66af), [`0xa08ca7c4…`](https://explorer-bradbury.genlayer.com/tx/0xa08ca7c40cb3d6d13bc110fc7a76509ed55197ab90ef474151f5ba37c4b7a2f5), [`0x189e366b…`](https://explorer-bradbury.genlayer.com/tx/0x189e366b0a86629541d0f4239f870d2381e12d423b9e814064465285f6c27ec6)). Afterwards `get_accounting` reports balance = expected = 0.001 GEN (mandate #1's restored budget), `unaccounted: 0`.

## What it does

| Layer | Mechanism | Depends on the LLM? |
|---|---|---|
| Hard limits | Escrowed budget, per-transaction cap, expiry; the agent cannot pay itself or the contract; optional delegator allowlist of recipients (`set_recipients`) | No |
| Review gating | After `review_every` spends, spending is blocked until a review runs (anyone — delegator, agent or a keeper — can trigger it) | No |
| Judgment | Validators fetch each receipt's evidence page and judge the spends against the objective and rubric | Yes, by consensus |
| Decision ladder | `continue` → full authority · `warn` → recorded, **2 warnings in a row escalate to `constrain`** · `constrain` → cap halved and evidence mandatory · `revoke` → frozen, one agent appeal, then refund · `escalate` → frozen until the delegator restores (under constraint, recorded as an override) or closes | Deterministic on top of the AI decision |
| Passive safety | `emergency_revoke` by the delegator at any time; `withdraw_remaining` after expiry | No |
| Payout ledger | Every vendor payment and refund is a payout, settled from its own transfer's on-chain result; a failed one is credited back, so nothing is lost | Consensus over chain data, no LLM |
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

## Payments, refunds and settlement

A value transfer from a GenLayer contract executes when the paying transaction
finalizes: the consensus contract calls this contract's ghost account on the
EVM layer, and the ghost emits `TransactionExecuted(to, msgId, data)` only if
the value call succeeded. So the contract never assumes a payment arrived, and
it judges each payment by its own transfer, never by its aggregate balance:

- `spend` and every refund (`emergency_revoke`, `withdraw_remaining`,
  `resolve_escalation(id, false)`, `recover`) first check the contract holds
  the amount, then record a **payout** (`get_payouts`) with the paying
  transaction's sender and creation time. One payout per sender per second,
  so that pair identifies the paying transaction.
- `settle_payout(payout_id, tx_hash, finalize_tx)`, callable by anyone, has
  validators read the chain and agree on the result:
  1. `gen_getTransactionReceipt(tx_hash)` must be this contract's, from the
     payout's sender at the payout's creation time, executed successfully and
     finalized, and its calldata must be the call that created this payout
     (method, mandate, and for `spend` the recipient and amount).
  2. `eth_getTransactionReceipt(finalize_tx)` must be the consensus
     transaction that emitted `TransactionFinalized(tx_hash)`.
  3. **DELIVERED** if that transaction holds this contract's
     `TransactionExecuted` to the payout's recipient, with a message id the
     messages contract links to `tx_hash`; otherwise **FAILED**.
- A FAILED vendor payment returns to the mandate's budget (and `spent` is
  reduced); the receipt stays, marked `FAILED`. A failed refund, or a payment
  that fails after the mandate closed, is credited to the delegator's
  `recoverable` balance, which `recover(id, to)` sends to any address.
- A payout settles once, and a paying transaction settles at most one payout.
- `get_accounting` (balance vs. expected) is an informational cross-check only.

The RPC URL and consensus contract addresses are Testnet Bradbury's
(constants at the top of the contract). A payee that is itself a GenLayer
contract is settled as delivered (its transfer becomes a separate
transaction); MandateGuard pays vendor and delegator accounts.

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
| `settle_payout(payout_id, tx_hash, finalize_tx)` | anyone | after the paying transaction finalizes; validators read its transfer result: DELIVERED, or FAILED and credited back |
| `recover(id, to)` | delegator | send the recoverable balance (failed refunds) to any address |
| `get_mandate`, `get_receipts`, `get_payouts`, `get_reviews`, `get_accounting`, `get_agent_record`, `get_mandate_count` | view | |

`examples/agent_supervisor.ts` shows an agent loop with genlayer-js and maps
the latest review to the Internet Court `AgentReviewDecision` payload.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
genvm-lint check contracts/mandate_guard.py
pytest tests/direct -v                         # 64 tests
# integration, on Bradbury, against the packed code (keys in GL_PK0..2 env vars)
python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
cd tests/integration && gltest . -v -s --network testnet_bradbury
```

### Deploying to Testnet Bradbury

The source is 43.4 KB; Bradbury rejects deploys above ~20 KB of code. Deploy
the output of `deploy/shrink.py` (AST-checked; 11.2 KB packed). CI re-runs all
64 direct tests against the packed code.

```bash
python deploy/shrink.py contracts/mandate_guard.py build/mandate_guard.py --pack
genlayer network && genlayer deploy --contract build/mandate_guard.py
```

## Tests (64 direct, 6-step Bradbury E2E)

- **Mandate lifecycle** — grant validation; spend receipts, transfers and events; hard limits independent of the LLM; review gating and keeper-triggered reviews; warn→warn escalation to constrain; constrained half-cap + mandatory evidence and recovery; revoke → appeal window → refund; successful appeal restores authority and reputation; failed appeal is final and not double counted; escalation restored or closed by the delegator; emergency revoke; expiry; top-up; decision events carry `permission_ref` with correctly bound indexed fields.
- **Consensus (validator replay)** — agrees with honest variation; rejects any different decision (including continue vs warn), criteria disagreement, a whitewashing leader, a griefing revoke, malformed/oversized payloads, fake transient errors and LLM errors; unknown labels revert; agent text and evidence are fenced; dead links don't block reviews.
- **Adversarial** (`test_safety.py`) — a delivered payment settles DELIVERED and validators reject a leader claiming failed; a failed one returns to the budget; a paying transaction settles only its own payout, once; settle rejects another sender, time, contract, method, amount or recipient, a reverted or unfinalized transaction, a finalization of another transaction, bad hashes and an unavailable RPC; one payment per sender per second; real recorded Bradbury receipts settle DELIVERED, and FAILED without the ghost's `TransactionExecuted`; spends revert when the contract cannot pay; failed refunds after emergency revoke, expiry withdraw and escalation close become recoverable and can be recovered once; double close is rejected; unauthorized and self-dealing spends; recipient allowlist; evidence commitment match, edited evidence binding validators, changed/unavailable statuses, explicit truncation; repeated escalation overrides never count as clearance; conflicting leader decisions are rejected.

- **Bradbury E2E** (`tests/integration`) — one mandate through warn → constrain (half cap and mandatory evidence enforced) → revoke → appeal upheld → refund; every spend and the refund settled DELIVERED after the recipient's balance is checked to rise by exactly the payout in the finalizing block; a spend to an EVM contract that rejects value settles FAILED, the recipient's balance does not move and the amount returns to the budget.

## License

MIT
