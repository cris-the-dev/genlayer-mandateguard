// Asserts which MandateGuard app controls appear per mandate state and role (run: node app/check-actions.mjs app/index.html).
import { readFileSync } from "node:fs";
const html = readFileSync(process.argv[2], "utf8");
const js = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
const body = js.slice(js.indexOf("function actions"), js.indexOf("async function show"));
const esc = (s) => String(s ?? "");
const gen = (w, d = 4) => (Number(w) / 1e18).toFixed(d).replace(/\.?0+$/, "");
const make = new Function("esc", "gen", "when", "LIVE", "ctx", `let me = ctx.me; ${body}; return actions;`);
const D = "0xd", A = "0xa", now = Date.now() / 1000;
const base = { delegator: D, agent: A, status: "ACTIVE", expires_at: now + 9999, review_due: false, spends_since_review: 0, effective_max_per_tx: "4000000000000000", appealed: false };
const run = (me, m) => make(esc, gen, () => "T", ["ACTIVE", "WARNED", "CONSTRAINED"], { me })({ ...base, ...m });
const check = (name, ok) => { console.log(ok ? "ok  " : "FAIL", name); if (!ok) process.exitCode = 1; };

check("no wallet: prompt only", run(null, {}).includes("Connect the delegator"));
check("outsider, nothing due: not a party", run("0xz", {}).includes("not a party"));
check("outsider can trigger a due review", run("0xz", { spends_since_review: 2, review_due: true }).includes('data-act="request_review"'));
check("agent active: spend form, evidence optional", /data-form="spend"/.test(run(A, {})) && !/name="evidence"[^>]*required/.test(run(A, {})));
check("agent constrained: evidence required", /name="evidence"[^>]*required/.test(run(A, { status: "CONSTRAINED" })));
check("agent, review due: no spend form", !run(A, { spends_since_review: 2, review_due: true }).includes('data-form="spend"'));
check("agent expired: no spend form", !run(A, { expires_at: now - 1 }).includes('data-form="spend"'));
check("agent revoked: appeal form once", run(A, { status: "REVOKED" }).includes("appeal_revocation") && !run(A, { status: "REVOKED", appealed: true }).includes("appeal_revocation"));
check("delegator escalated: restore and close", (run(D, { status: "ESCALATED" }).match(/resolve_escalation/g) || []).length === 2);
check("delegator live: withdraw disabled before expiry", /withdraw_remaining"[^>]*disabled/.test(run(D, {})));
check("delegator revoked: withdraw enabled, no top-up", /withdraw_remaining"(?![^>]*disabled)/.test(run(D, { status: "REVOKED" })) && !run(D, { status: "REVOKED" }).includes("top_up"));
check("delegator: emergency revoke until closed", run(D, {}).includes("emergency_revoke") && !run(D, { status: "CLOSED" }).includes("emergency_revoke"));
