// Shared wallet + contract helpers for the demo apps (testnet Bradbury, MetaMask).
import { createClient, testnetBradbury } from "./genlayer.js"; // bundle of genlayer-js 1.1.8 (see README);

export const EXPLORER = "https://explorer-bradbury.genlayer.com";
const CHAIN_HEX = "0x" + testnetBradbury.id.toString(16);

export const plain = (v) =>
  v instanceof Map ? Object.fromEntries([...v].map(([k, x]) => [String(k), plain(x)]))
  : Array.isArray(v) ? v.map(plain)
  : typeof v === "bigint" ? Number(v) : v;

const reader = createClient({ chain: testnetBradbury });
let account = null;

export function contract(address) {
  return {
    read: async (functionName, args = []) => plain(await reader.readContract({ address, functionName, args })),
    // Sends a tx through MetaMask and waits until validators accept it.
    write: async (functionName, args = [], value = 0n, onHash) => {
      if (!account) throw new Error("Connect a wallet first");
      const client = createClient({ chain: testnetBradbury, account });
      const hash = await client.writeContract({ address, functionName, args, value });
      onHash?.(hash);
      // Poll ourselves so timeouts stop the wait instead of hanging until retries run out.
      for (let i = 0; i < 120; i++) {
        const t = await client.getTransaction({ hash });
        const s = t.statusName ?? t.status_name ?? String(t.status);
        if (s === "ACCEPTED" || s === "FINALIZED") {
          if ((t.txExecutionResultName ?? t.tx_execution_result_name) === "FINISHED_WITH_ERROR") {
            throw new Error("The contract rejected this transaction. Check the inputs and try again.");
          }
          return t;
        }
        if (["LEADER_TIMEOUT", "VALIDATORS_TIMEOUT", "UNDETERMINED", "CANCELED"].includes(s)) {
          throw new Error(`Validators did not reach a decision (${s}). Nothing changed on-chain; try again.`);
        }
        await new Promise((ok) => setTimeout(ok, 5000));
      }
      throw new Error("Still waiting for validators after 10 minutes. Check the transaction in the explorer.");
    },
  };
}

export async function connect() {
  const eth = window.ethereum;
  if (!eth) throw new Error("No wallet found. Install MetaMask to send transactions; reading works without one.");
  [account] = await eth.request({ method: "eth_requestAccounts" });
  if ((await eth.request({ method: "eth_chainId" })).toLowerCase() !== CHAIN_HEX) {
    try {
      await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: CHAIN_HEX }] });
    } catch (e) {
      if (e.code !== 4902) throw e;
      await eth.request({ method: "wallet_addEthereumChain", params: [{
        chainId: CHAIN_HEX, chainName: "GenLayer Bradbury Testnet",
        nativeCurrency: { name: "GEN", symbol: "GEN", decimals: 18 },
        rpcUrls: testnetBradbury.rpcUrls.default.http, blockExplorerUrls: [EXPLORER],
      }] });
    }
  }
  return account;
}

export const short = (a) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : "");
export const gen = (wei, d = 4) => (Number(wei) / 1e18).toFixed(d).replace(/\.?0+$/, "") || "0";
export const toWei = (s) => {
  const [i, f = ""] = String(s).trim().split(".");
  return BigInt(i || "0") * 10n ** 18n + BigInt((f + "0".repeat(18)).slice(0, 18) || "0");
};
export const ago = (ts) => {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  return s < 90 ? `${s}s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
export const $ = (sel) => document.querySelector(sel);

// Wire the header "Connect wallet" button and a status line for tx progress.
export function wireWallet(onConnected) {
  const btn = $("#connect");
  btn.addEventListener("click", async () => {
    try {
      const a = await connect();
      btn.textContent = short(a);
      btn.disabled = true;
      onConnected?.(a);
    } catch (e) { status(e.message, true); }
  });
}

export function status(msg, isError = false, hash) {
  const el = $("#status");
  el.hidden = !msg;
  el.className = isError ? "status err" : "status";
  el.innerHTML = esc(msg) + (hash ? ` <a href="${EXPLORER}/tx/${hash}">view tx ↗</a>` : "");
}

// Run a write with consistent status messages; returns true on success.
export async function send(c, label, fn, args, value = 0n) {
  status(`${label}: confirm in your wallet…`);
  try {
    await c.write(fn, args, value, (h) => status(`${label}: waiting for validators to agree (this can take a minute)…`, false, h));
    status(`${label}: done.`);
    return true;
  } catch (e) {
    status(`${label}: ${e.shortMessage ?? e.message}`, true);
    return false;
  }
}
