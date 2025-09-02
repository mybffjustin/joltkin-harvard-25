// frontend/react_app/src/components/BuyResalePanel.tsx
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2025 Joltkin LLC.

/**
 * BuyResalePanel
 *
 * Minimal, demo-oriented UI that assembles a 3-transaction Algorand group
 * for either a primary buy or a resale via the “Royalty Router” app:
 *
 *   1) ApplicationCall (NoOp) — appArgs: ["buy"] or ["resale"]
 *   2) Payment               — buyer -> app address (price in µAlgos)
 *   3) AssetTransfer         — ticket (ASA) 1 unit (seller -> buyer)
 *
 * Notes:
 *  - For simplicity, this demo has the connected wallet sign *all three* txns.
 *    In production, the seller/current holder MUST sign tx #3 (ASA transfer)
 *    from *their* wallet, not the buyer’s wallet.
 *  - The ApplicationCall uses a flat fee to cover inner transactions performed
 *    by the router (splits/royalty). Fee levels are conservative and should
 *    be revisited alongside contract logic & network params.
 *  - The router contract also expects specific accounts arrays in the AppCall
 *    for payout recipients. This demo omits those to keep the flow minimal;
 *    the contract you deploy must either not require them or compute them
 *    from global state.
 */

import React, { useEffect, useMemo, useState } from 'react'
import algosdk, { SuggestedParams } from 'algosdk'
import { useWallet } from '../wallet'
import {
  useAlgod,
  signAndSend,
  ROUTER_APP_ID,
  TICKET_ASA_ID,
} from '../lib/algorand'

/**
 * Fee notes:
 * - The Algorand JS SDK expects `suggestedParams.fee` as a **number** (microAlgos).
 * - App calls that execute inner transactions must pay for those inner ops.
 *   We set a flat fee on the app call to cover them; tune these for your contract.
 */
const BUY_APP_FEE_UALGOS = 3000 // ~3 inner payments
const RESALE_APP_FEE_UALGOS = 2000 // tune to your router’s inner ops

type Flow = 'buy' | 'resale'

export default function BuyResalePanel() {
  const algod = useAlgod()
  const { address, pera } = useWallet()

  // Inputs / state
  const [appId, setAppId] = useState<number>(ROUTER_APP_ID)
  const [asaId, setAsaId] = useState<number>(TICKET_ASA_ID)
  const [price, setPrice] = useState<number>(1_000_000) // µAlgos
  const [busy, setBusy] = useState<Flow | undefined>(undefined)

  // “Real world” vs demo self-transfer (seller->buyer in one wallet)
  const [demoSelfTransfer, setDemoSelfTransfer] = useState<boolean>(true)
  const [sellerAddr, setSellerAddr] = useState<string>('') // populated from wallet if demo=false
  const [buyerAddr, setBuyerAddr] = useState<string>('')  // populated from wallet by default

  // Derived: app escrow address
  const appAddr = useMemo(() => {
    try {
      return appId ? algosdk.getApplicationAddress(appId) : ''
    } catch {
      return ''
    }
  }, [appId])

  // Default fields from connected wallet
  useEffect(() => {
    if (!address) return
    if (demoSelfTransfer) {
      setSellerAddr(address)
      setBuyerAddr(address)
    } else {
      // if toggled off from demo mode, keep buyer defaulting to current wallet
      if (!buyerAddr) setBuyerAddr(address)
      // leave seller empty so user can paste the real holder
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address, demoSelfTransfer])

  // Quick receiver (buyer) opt-in probe for the ASA
  const [buyerOptedIn, setBuyerOptedIn] = useState<boolean | null>(null)
  useEffect(() => {
    let cancelled = false
    async function check() {
      setBuyerOptedIn(null)
      try {
        if (!buyerAddr || !asaId) return
        await algod.accountAssetInformation(buyerAddr, asaId).do()
        if (!cancelled) setBuyerOptedIn(true)
      } catch (e: any) {
        // If not opted-in or asset not found, the endpoint throws (404)
        if (!cancelled) setBuyerOptedIn(false)
      }
    }
    check()
    return () => {
      cancelled = true
    }
  }, [algod, buyerAddr, asaId])

  // Simple guards
  const numericOk = appId > 0 && asaId > 0 && price > 0
  const haveWallet = !!address
  const canSubmit = haveWallet && numericOk && !!appAddr && !!buyerAddr && !!sellerAddr && !busy

  const formatAlgo = (u: number) => (u / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 6 })

  async function run(which: Flow) {
    try {
      if (!canSubmit) throw new Error('Fill all fields and connect a wallet')

      setBusy(which)

      // Prepare suggested params
      const spApp: SuggestedParams = await algod.getTransactionParams().do()
      spApp.flatFee = true
      spApp.fee = which === 'buy' ? BUY_APP_FEE_UALGOS : RESALE_APP_FEE_UALGOS

      const spPay = await algod.getTransactionParams().do()
      const spAsa = await algod.getTransactionParams().do()

      const appCall = algosdk.makeApplicationNoOpTxnFromObject({
        sender: address!, // the connected wallet triggers the router
        appIndex: appId,
        suggestedParams: spApp,
        appArgs: [new TextEncoder().encode(which)], // "buy" | "resale"
        // If your router expects payout recipients via Txn.accounts,
        // add them below, e.g.: accounts: [artist, venue, platform, seller]
        // accounts,
      })

      // (2) Payment — buyer -> router’s escrow address
      const pay = algosdk.makePaymentTxnWithSuggestedParamsFromObject({
        sender: buyerAddr,
        receiver: appAddr,
        amount: price, // µAlgos
        suggestedParams: spPay,
      })

      // (3) AssetTransfer — ONE ticket unit (seller -> buyer)
      const asaXfer = algosdk.makeAssetTransferTxnWithSuggestedParamsFromObject({
        sender: sellerAddr,
        receiver: buyerAddr,
        amount: 1,
        assetIndex: asaId,
        suggestedParams: spAsa,
      })

      // IMPORTANT: In production this is a multi-signer group.
      // For the demo we let one wallet sign all txns. Your `signAndSend`
      // should set the group ID, fan out for signatures (e.g., via Pera),
      // then submit + wait for confirmation.
      const txid = await signAndSend(pera, address!, [appCall, pay, asaXfer], algod)

      alert(`${which} submitted: ${txid}`)
    } catch (e: any) {
      // Common pitfalls → nicer messages
      const msg = String(e?.message || e)
      if (/overspend/i.test(msg)) {
        alert('Not enough balance to cover price + fees.')
      } else if (/must optin/i.test(msg) || /asset holding/i.test(msg)) {
        alert('Buyer must be opted in to the ticket ASA before receiving it.')
      } else {
        alert(msg)
      }
      console.error(e)
    } finally {
      setBusy(undefined)
    }
  }

  return (
    <div className="card" aria-busy={!!busy}>
      <h3 style={{ marginTop: 0 }}>Ticket Buy / Resale (Router)</h3>

      {/* Router / asset / price */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
        <div>
          <label htmlFor="router-id">Router App ID</label>
          <input
            id="router-id"
            inputMode="numeric"
            value={appId || ''}
            onChange={(e) => setAppId(Number(e.target.value) || 0)}
          />
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>
            App address: <code>{appAddr || '—'}</code>
          </div>
        </div>

        <div>
          <label htmlFor="asa-id">Ticket ASA ID</label>
          <input
            id="asa-id"
            inputMode="numeric"
            value={asaId || ''}
            onChange={(e) => setAsaId(Number(e.target.value) || 0)}
          />
        </div>

        <div>
          <label htmlFor="price">Price (µAlgos)</label>
          <input
            id="price"
            inputMode="numeric"
            value={price || ''}
            onChange={(e) => setPrice(Number(e.target.value) || 0)}
          />
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>
            ≈ {formatAlgo(price)} ALGO
          </div>
        </div>
      </div>

      {/* Parties */}
      <fieldset style={{ marginTop: 16 }}>
        <legend style={{ fontSize: 14, opacity: 0.8 }}>Parties</legend>

        <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <input
            type="checkbox"
            checked={demoSelfTransfer}
            onChange={(e) => setDemoSelfTransfer(e.target.checked)}
          />
          Demo self-transfer (seller = buyer = connected wallet)
        </label>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <label htmlFor="seller">Seller (ASA sender)</label>
            <input
              id="seller"
              placeholder="ADDR…"
              value={sellerAddr}
              onChange={(e) => setSellerAddr(e.target.value.trim())}
              disabled={demoSelfTransfer}
            />
          </div>

          <div>
            <label htmlFor="buyer">Buyer (ALGO payer & ASA recipient)</label>
            <input
              id="buyer"
              placeholder="ADDR…"
              value={buyerAddr}
              onChange={(e) => setBuyerAddr(e.target.value.trim())}
              disabled={demoSelfTransfer}
            />
            {buyerAddr && buyerOptedIn === false && (
              <div style={{ color: '#c00', fontSize: 12, marginTop: 4 }}>
                Buyer is <strong>not opted-in</strong> to ASA {asaId}. They must opt-in before receiving the ticket.
              </div>
            )}
            {buyerAddr && buyerOptedIn === true && (
              <div style={{ color: '#0a7', fontSize: 12, marginTop: 4 }}>
                Buyer is opted-in to ASA {asaId}.
              </div>
            )}
          </div>
        </div>
      </fieldset>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
        <button onClick={() => run('buy')} disabled={!canSubmit || busy === 'buy'}>
          {busy === 'buy' ? 'Buying…' : 'Run Buy (demo)'}
        </button>
        <button onClick={() => run('resale')} disabled={!canSubmit || busy === 'resale'}>
          {busy === 'resale' ? 'Reselling…' : 'Run Resale (demo)'}
        </button>
      </div>

      <p style={{ marginTop: 12, fontSize: 12, opacity: 0.75, lineHeight: 1.35 }}>
        <strong>Demo caveat:</strong> This UI can run in “self-transfer” mode for convenience.
        In production, the <em>seller</em> (current holder) must sign the ASA transfer,
        and the <em>buyer</em> pays the ALGO price. Your wallet integration should gather both signatures
        for the grouped transactions before submission.
      </p>
    </div>
  )
}
