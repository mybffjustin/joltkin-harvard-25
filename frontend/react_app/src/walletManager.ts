// frontend/react_app/src/walletManager.ts
// Purpose: Wallet bootstrap + helpers to build, sign, submit, and confirm Algorand txns

import algosdk from "algosdk";
import { WalletManager, WalletId, NetworkId } from "@txnlab/use-wallet";

const ALGOD_URL =
  import.meta.env.VITE_ALGOD_URL ?? "https://testnet-api.algonode.cloud";
const ALGOD_TOKEN = import.meta.env.VITE_ALGOD_TOKEN ?? "";

export const algod = new algosdk.Algodv2(ALGOD_TOKEN, ALGOD_URL);

export const manager = new WalletManager({
  wallets: [WalletId.PERA, WalletId.DEFLY],
  defaultNetwork: NetworkId.TESTNET,
});

/** Set a flat fee compatibly across SDK versions (number or bigint). */
function setFlatFee(sp: algosdk.SuggestedParams, fee: number) {
  const anySp = sp as any;
  anySp.flatFee = true;
  const currentFee = anySp.fee;
  anySp.fee = typeof currentFee === "bigint" ? BigInt(fee) : fee;
}

export async function suggestedParamsFlat(
  fee: number = 4000
): Promise<algosdk.SuggestedParams> {
  const sp = await algod.getTransactionParams().do();
  setFlatFee(sp, fee);
  return sp;
}

export async function waitForConfirmation(
  txid: string,
  maxRounds = 32
): Promise<Record<string, any>> {
  const status = await algod.status().do();
  // SDK’s TS types use camelCase (lastRound / confirmedRound)
  let last = Number(status.lastRound);
  for (let i = 0; i < maxRounds; i++) {
    const info = await algod.pendingTransactionInformation(txid).do();
    const confirmed = info.confirmedRound;
    if (confirmed && confirmed > 0) return info as Record<string, any>;
    last += 1;
    await algod.statusAfterBlock(last).do();
  }
  throw new Error(`Transaction ${txid} not confirmed after ${maxRounds} rounds`);
}

export function explainError(e: any): string {
  const msg = String(e?.message || e);
  if (msg.includes("getEncodingSchema") || msg.includes("get_obj_for_encoding")) {
    return "Encoding error: encodeUnsignedTransaction() before signTransactions().";
  }
  if (msg.includes("Cannot read properties of undefined") && msg.includes("sign")) {
    return "No wallet connected. Connect a wallet first.";
  }
  if (msg.includes("overspend") || msg.includes("below min")) {
    return "Balance/MBR too low. Fund the account/app and retry.";
  }
  return msg;
}

/** Sign a grouped set of txns, submit, wait. */
export async function signSubmitConfirm(
  txns: algosdk.Transaction[]
): Promise<{ txid: string; confirmed: Record<string, any> }> {
  if (!txns.length) throw new Error("No transactions to sign.");

  algosdk.assignGroupID(txns);
  const unsigned = txns.map((t) => algosdk.encodeUnsignedTransaction(t));

  const active = (manager as any).activeWallet;
  if (!active) throw new Error("Connect a wallet to sign.");

  const signedMaybe = await active.signTransactions(unsigned); // (Uint8Array|null)[]
  const signed = signedMaybe.filter((b: any): b is Uint8Array => b !== null);
  if (signed.length !== unsigned.length) {
    throw new Error("Transaction signing cancelled or failed for one or more transactions.");
  }

  const post: any = await algod.sendRawTransaction(signed).do();
  // Be defensive about field name variations across SDK versions
  const txid: string =
    post?.txId ?? post?.txid ?? post?.txID ?? post?.txidString ?? "";

  if (!txid) throw new Error("Could not determine transaction id after submit.");

  const confirmed = await waitForConfirmation(txid);
  return { txid, confirmed };
}

// ── Superfan helpers ──────────────────────────────────────────────────────────

export async function makeSuperfanOptIn(
  senderAddr: string,
  appId: number,
  fee: number = 1000
): Promise<algosdk.Transaction> {
  const sp = await algod.getTransactionParams().do();
  setFlatFee(sp, fee);
  return algosdk.makeApplicationOptInTxnFromObject({
    // use `sender` here to satisfy older TS typings
    sender: senderAddr,
    appIndex: appId,
    suggestedParams: sp,
  });
}

export async function makeSuperfanAddPoints(
  adminAddr: string,
  appId: number,
  points: number,
  targetAddr: string,
  fee: number = 4000
): Promise<algosdk.Transaction> {
  const sp = await algod.getTransactionParams().do();
  setFlatFee(sp, fee);
  const args = [
    new Uint8Array(Buffer.from("add_points")),
    algosdk.encodeUint64(points),
  ];
  return algosdk.makeApplicationNoOpTxnFromObject({
    sender: adminAddr,            // `sender` for TS compatibility
    appIndex: appId,
    appArgs: args,
    accounts: [targetAddr],       // becomes Txn.accounts[1] in TEAL
    suggestedParams: sp,
  });
}

export async function makeSuperfanClaimTier(
  fanAddr: string,
  appId: number,
  threshold: number,
  fee: number = 4000
): Promise<algosdk.Transaction> {
  const sp = await algod.getTransactionParams().do();
  setFlatFee(sp, fee);
  const args = [
    new Uint8Array(Buffer.from("claim_tier")),
    algosdk.encodeUint64(threshold),
  ];
  return algosdk.makeApplicationNoOpTxnFromObject({
    sender: fanAddr,              // `sender` for TS compatibility
    appIndex: appId,
    appArgs: args,
    suggestedParams: sp,
  });
}

export async function superfanOptInAndConfirm(sender: string, appId: number) {
  try {
    const tx = await makeSuperfanOptIn(sender, appId);
    return await signSubmitConfirm([tx]);
  } catch (e) {
    throw new Error(explainError(e));
  }
}

export async function superfanAddPointsAndConfirm(
  admin: string,
  appId: number,
  points: number,
  target: string
) {
  try {
    const tx = await makeSuperfanAddPoints(admin, appId, points, target);
    return await signSubmitConfirm([tx]);
  } catch (e) {
    throw new Error(explainError(e));
  }
}

export async function superfanClaimTierAndConfirm(
  fan: string,
  appId: number,
  threshold: number
) {
  try {
    const tx = await makeSuperfanClaimTier(fan, appId, threshold);
    return await signSubmitConfirm([tx]);
  } catch (e) {
    throw new Error(explainError(e));
  }
}

/** App address as string (older TS types don’t accept Address). */
export function appAddress(appId: number): string {
  return algosdk.getApplicationAddress(appId).toString();
}

export function fmtAlgo(micros: number | bigint): string {
  const n = typeof micros === "bigint" ? Number(micros) : micros;
  return (n / 1e6).toFixed(6);
}
