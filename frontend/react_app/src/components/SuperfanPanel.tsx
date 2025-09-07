// frontend/react_app/src/components/SuperfanPanel.tsx
// SPDX-License-Identifier: Apache-2.0
// © 2025 Joltkin LLC.

import { useEffect, useMemo, useState } from "react";
import algosdk, { SuggestedParams } from "algosdk";
import { useWallet } from "../wallet"; // your local wallet hook (address only)
import { useAlgod, SUPERFAN_APP_ID, SUPERFAN_ADMIN_ADDR } from "../lib/algorand";
import { signSubmitConfirm } from "../walletManager";

/**
 * Minimal demo UI for Superfan contract:
 *  - Opt-in (creates local state)
 *  - Claim tier (if pts >= threshold)
 *  - Add points (admin only; accounts[0] → Txn.accounts[1] in TEAL)
 */

type Busy = undefined | "loading" | "optin" | "claim" | "add" | "refresh";

export default function SuperfanPanel() {
  const algod = useAlgod();
  const { address } = useWallet();

  // Form/flow state
  const [appId, setAppId] = useState<number>(SUPERFAN_APP_ID);
  const [threshold, setThreshold] = useState<number>(100);
  const [points, setPoints] = useState<number>(10);
  const [targetAddr, setTargetAddr] = useState<string>("");
  const [busy, setBusy] = useState<Busy>();
  const [msg, setMsg] = useState<string>("");

  const isAdmin = useMemo(() => !!address && address === SUPERFAN_ADMIN_ADDR, [address]);

  // Local state from chain
  const [localPts, setLocalPts] = useState<number | null>(null);
  const [localTier, setLocalTier] = useState<number | null>(null);

  // ── helpers ────────────────────────────────────────────────────────────────
  const note = (text: string) => setMsg(text);
  const clearNoteSoon = () => setTimeout(() => setMsg(""), 2500);

  const setFlatFee = (sp: SuggestedParams, fee: number) => {
    (sp as any).flatFee = true;
    (sp as any).fee = typeof (sp as any).fee === "bigint" ? BigInt(fee) : fee;
  };

  const fetchLocalState = async () => {
    if (!address || !appId) return;
    setBusy("refresh");
    setMsg("Reading local state…");
    try {
      const info = await algod.accountApplicationInformation(address, appId).do();

      // support modern (appLocalState/keyValue) and legacy (app-local-state/key-value) shapes
      const local =
        (info as any).appLocalState ?? (info as any)["app-local-state"] ?? {};
      const kv:
        | Array<{ key: string; value: { bytes: string; uint: number; type: number } }>
        = (local as any).keyValue ?? (local as any)["key-value"] ?? [];

      const readUint = (lookupKey: string): number | null => {
        for (const item of kv) {
          const decoded = typeof atob === "function" ? atob(item.key) : "";
          if (decoded === lookupKey) return Number(item.value?.uint ?? 0);
        }
        return null;
      };

      setLocalPts(readUint("pts"));
      setLocalTier(readUint("tier"));
      setMsg("Local state refreshed ✓");
    } catch (e: any) {
      console.error(e);
      setMsg(e?.message || "Failed to read local state");
    } finally {
      setBusy(undefined);
      clearNoteSoon();
    }
  };

  // ── actions ────────────────────────────────────────────────────────────────
  const optin = async () => {
    try {
      if (!address) throw new Error("Connect wallet");
      if (!appId || appId <= 0) throw new Error("Provide a valid App ID");

      setBusy("optin");
      note("Submitting opt-in…");

      const sp = await algod.getTransactionParams().do();
      const txn = algosdk.makeApplicationOptInTxnFromObject({
        sender: address,
        appIndex: appId,
        suggestedParams: sp,
      });

      await signSubmitConfirm([txn]);
      note("Opt-in submitted ✓");
      await fetchLocalState();
    } catch (e: any) {
      console.error(e);
      note(e?.message || String(e));
    } finally {
      setBusy(undefined);
      clearNoteSoon();
    }
  };

  const claim = async () => {
    try {
      if (!address) throw new Error("Connect wallet");
      if (!appId || appId <= 0) throw new Error("Provide a valid App ID");
      if (threshold < 0) throw new Error("Threshold must be ≥ 0");

      setBusy("claim");
      note("Submitting claim…");

      const sp = await algod.getTransactionParams().do();
      const appArgs = [
        new TextEncoder().encode("claim_tier"),
        algosdk.encodeUint64(threshold),
      ];

      const txn = algosdk.makeApplicationNoOpTxnFromObject({
        sender: address,
        appIndex: appId,
        suggestedParams: sp,
        appArgs,
      });

      await signSubmitConfirm([txn]);
      note("Claim submitted ✓");
      await fetchLocalState();
    } catch (e: any) {
      console.error(e);
      note(e?.message || String(e));
    } finally {
      setBusy(undefined);
      clearNoteSoon();
    }
  };

  const addPoints = async () => {
    try {
      if (!address) throw new Error("Connect wallet");
      if (!isAdmin) throw new Error("Connect the admin wallet to add points");
      if (!appId || appId <= 0) throw new Error("Provide a valid App ID");
      if (points <= 0) throw new Error("Points must be > 0");

      const target = (targetAddr || address).trim();
      if (!algosdk.isValidAddress(target)) {
        throw new Error("Target address is not a valid Algorand address");
      }

      setBusy("add");
      note("Submitting add_points…");

      const sp = await algod.getTransactionParams().do();
      setFlatFee(sp, 1000);

      const appArgs = [
        new TextEncoder().encode("add_points"),
        algosdk.encodeUint64(points),
      ];

      // accounts[0] here → Txn.accounts[1] in TEAL
      const txn = algosdk.makeApplicationNoOpTxnFromObject({
        sender: address, // admin
        appIndex: appId,
        suggestedParams: sp,
        appArgs,
        accounts: [target],
      });

      await signSubmitConfirm([txn]);
      note("Points submitted ✓");
      if (target === address) await fetchLocalState();
    } catch (e: any) {
      console.error(e);
      note(e?.message || String(e));
    } finally {
      setBusy(undefined);
      clearNoteSoon();
    }
  };

  // Auto-refresh on connect/app change
  useEffect(() => {
    if (address && appId) {
      fetchLocalState();
    } else {
      setLocalPts(null);
      setLocalTier(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address, appId]);

  // ── UI ─────────────────────────────────────────────────────────────────────
  return (
    <div className="card" aria-busy={!!busy}>
      <div
        style={{
          display: "flex",
          gap: 16,
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <div style={{ fontSize: 13, opacity: 0.8 }}>
          <div>
            <strong>Local pts:</strong>{" "}
            {localPts ?? <em style={{ opacity: 0.6 }}>—</em>}
          </div>
          <div>
            <strong>Local tier:</strong>{" "}
            {localTier ?? <em style={{ opacity: 0.6 }}>—</em>}
          </div>
        </div>
        <button onClick={fetchLocalState} disabled={!address || busy === "refresh"}>
          {busy === "refresh" ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 12 }}>
        <div>
          <label htmlFor="sf-app-id">Superfan App ID</label>
          <input
            id="sf-app-id"
            inputMode="numeric"
            value={appId || ""}
            onChange={(e) => setAppId(Number(e.target.value) || 0)}
          />
        </div>

        <div>
          <label htmlFor="sf-threshold">Tier Threshold</label>
          <input
            id="sf-threshold"
            inputMode="numeric"
            value={threshold || ""}
            onChange={(e) => setThreshold(Number(e.target.value) || 0)}
          />
        </div>

        <div>
          <label htmlFor="sf-points">Points to Add (admin)</label>
          <input
            id="sf-points"
            inputMode="numeric"
            value={points || ""}
            onChange={(e) => setPoints(Number(e.target.value) || 0)}
          />
        </div>

        <div>
          <label htmlFor="sf-target">Target Address (optional)</label>
          <input
            id="sf-target"
            placeholder="Defaults to sender"
            value={targetAddr}
            onChange={(e) => setTargetAddr(e.target.value)}
          />
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginTop: 16, flexWrap: "wrap" }}>
        <button onClick={optin} disabled={!address || busy === "optin"}>
          {busy === "optin" ? "Opting in…" : "Opt-in"}
        </button>
        <button onClick={claim} disabled={!address || busy === "claim"}>
          {busy === "claim" ? "Claiming…" : "Claim Tier"}
        </button>
        <button
          onClick={addPoints}
          disabled={!address || !isAdmin || busy === "add"}
          title={isAdmin ? "" : "Connect the admin wallet to enable"}
        >
          {busy === "add" ? "Adding…" : "Admin: Add Points"}
        </button>
      </div>

      {!!msg && (
        <div
          role="status"
          aria-live="polite"
          style={{
            marginTop: 12,
            fontSize: 12,
            padding: "8px 10px",
            borderRadius: 8,
            background: "rgba(0,0,0,.04)",
          }}
        >
          {msg}
        </div>
      )}

      <p style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>
        Demo only — fees/logic are conservative. Replace alerts with real toasts and
        derive admin from contract state in production.
      </p>
    </div>
  );
}
