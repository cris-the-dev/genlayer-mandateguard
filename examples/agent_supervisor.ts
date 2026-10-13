/**
 * MandateGuard from an agent / controller point of view (genlayer-js).
 *
 *   npx tsx examples/agent_supervisor.ts
 *
 * Env: PRIVATE_KEY (agent), MANDATEGUARD_ADDRESS, MANDATE_ID
 *
 * - The agent spends through the contract, attaching a purpose and evidence.
 * - When a review is due it requests one (any keeper could).
 * - `toInternetCourtDecision` maps the latest review to the Internet Court
 *   `AgentReviewDecision` shape, so a revocation controller (e.g. for an
 *   ERC-7710 delegation identified by `permission_ref`) can enforce it.
 */
import { createAccount, createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import type { CalldataEncodable } from "genlayer-js/types";

const client = createClient({
  chain: testnetBradbury,
  account: createAccount(process.env.PRIVATE_KEY as `0x${string}`),
});
const address = (process.env.MANDATEGUARD_ADDRESS ?? "0x023e18d8b4feD3b62495Cb19c384ecD1E0113BeD") as `0x${string}`;
const mandateId = Number(process.env.MANDATE_ID ?? 0);

const toPlain = (v: any): any =>
  v instanceof Map
    ? Object.fromEntries([...v.entries()].map(([k, x]) => [String(k), toPlain(x)]))
    : Array.isArray(v)
      ? v.map(toPlain)
      : v;

const read = async (functionName: string, args: CalldataEncodable[] = []) =>
  toPlain(await client.readContract({ address, functionName, args }));

async function write(functionName: string, args: CalldataEncodable[]) {
  const hash = await client.writeContract({ address, functionName, args, value: 0n });
  return client.waitForTransactionReceipt({ hash, status: "ACCEPTED" as any, retries: 60, interval: 5000 });
}

export type AgentReviewDecision = {
  mandateId: string;
  decision: "continue" | "warn" | "constrain" | "revoke" | "escalate";
  score: number;
  reasoning: string;
  violations: string[];
  constraints?: { maxPerTxWei?: string; requireEvidence?: boolean };
  reviewedActionIds: string[];
  issuedAt: string;
  permissionRef: string;
};

export function toInternetCourtDecision(mandate: any, reviews: any[]): AgentReviewDecision | null {
  const r = reviews.at(-1);
  if (!r) return null;
  const firstReviewed = Number(mandate.receipt_count) - Number(r.reviewed_receipts);
  return {
    mandateId: `mandateguard:${address}:${mandate.id}`,
    decision: r.decision,
    score: Math.round((100 * Number(r.criteria_met)) / Math.max(1, Number(r.criteria_total))),
    reasoning: r.reasoning,
    violations: r.violations,
    constraints:
      r.decision === "constrain"
        ? { maxPerTxWei: String(mandate.effective_max_per_tx), requireEvidence: true }
        : undefined,
    reviewedActionIds: Array.from({ length: Number(r.reviewed_receipts) }, (_, i) => `${mandate.id}:${firstReviewed + i}`),
    issuedAt: new Date(Number(r.at) * 1000).toISOString(),
    permissionRef: mandate.permission_ref,
  };
}

async function main() {
  let mandate = await read("get_mandate", [mandateId]);
  if (mandate.review_due) {
    console.log("Review due — requesting one…");
    await write("request_review", [mandateId]);
    mandate = await read("get_mandate", [mandateId]);
  }
  if (["ACTIVE", "WARNED", "CONSTRAINED"].includes(mandate.status)) {
    await write("spend", [
      mandateId,
      "0x000000000000000000000000000000000000dEaD",
      1n,
      "Example spend: 1 wei test transfer",
      "https://example.com/",
      "", // optional sha256 of the evidence text, binding validators to this exact page
    ]);
  }
  const reviews = await read("get_reviews", [mandateId]);
  console.log(JSON.stringify(toInternetCourtDecision(mandate, reviews), null, 2));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
