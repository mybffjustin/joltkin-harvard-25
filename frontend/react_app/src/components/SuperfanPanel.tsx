// frontend/react_app/src/components/SuperfanPanel.tsx
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2025 Joltkin LLC.

/**
 * SuperfanPanel
 *
 * A minimal demo UI for interacting with the Superfan smart contract:
 * - Opt-in:   Initializes local state for the connected wallet.
 * - Claim:    Attempts to set the user's tier if their on-chain points
 *             are >= a provided threshold (contract enforces this).
 * - AddPoints (admin-only): Adds points to a target account (self in this demo).
 *
 * Contract expectations (per `contracts/superfan_pass.py`):
 * - `optin` initializes local keys: {"pts": 0, "tier": 0}.
 * - `claim_tier(threshold)` validates `local.pts >= threshold` and sets `local.tier`.
 * - `add_points(amount)` is admin-gated and increments points for:
 *     - Txn.accounts[1] *if provided*, otherwise Txn.sender().
 *   NOTE: In TEAL, `Txn.accounts[0]` is always the sender. The *first foreign
 *   account* is `Txn.accounts[1]`. In algosdk, you pass this via
 *   `accounts: [<address>]`, which the contract then sees as `Txn.accounts[1]`.
 *
 * Security / prod notes:
 * - This demo uses alerts for UX; replace with real notifications.
 * - It assumes the Superfan admin address is known via env/config; real apps
 *   should derive admin from contract global state (read via indexer/algod).
 * - Network fee values should be tuned alongside the contract’s inner operations.
 */

import { useEffect, useMemo, useState } from 'react'
import algosdk from 'algosdk'
import { useWallet } from '../wallet'
import {
  useAlgod,
  SUPERFAN_APP_ID,
  SUPERFAN_ADMIN_ADDR,
  signAndSend,
} from '../lib/algorand'

/**
 * SuperfanPanel
 *
 * Minimal demo UI for interacting with the Superfan smart contract:
 *  - Opt-in (creates local state)
 *  - Claim tier (if pts >= threshold)
 *  - Add points (admin gated)
 *
 * Enhancements:
 *  - Live read of local state (pts, tier) with a Refresh button.
 *  - Target address field for Add Points (defaults to self).
 *  - Safer fee handling (number, flat fee).
 *  - Basic client-side validation + inline status messages.
 */

type Busy =
  | undefined
  | 'loading'
  | 'optin'
  | 'claim'
  | 'add'
  | 'refresh'

export default function SuperfanPanel() {
  // Wallet + Algod
  const { address, pera } = useWallet()
  const algod = useAlgod()

  // Form/flow state
  const [appId, setAppId] = useState<number>(SUPERFAN_APP_ID)
  const [threshold, setThreshold] = useState<number>(100)
  const [points, setPoints] = useState<number>(10)
  const [targetAddr, setTargetAddr] = useState<string>('') // defaults to self in submit path
  const [busy, setBusy] = useState<Busy>()
  const [msg, setMsg] = useState<string>('')

  // Derived
  const isAdmin = useMemo(
    () => !!address && address === SUPERFAN_ADMIN_ADDR,
    [address]
  )

  // Local state from chain
  const [localPts, setLocalPts] = useState<number | null>(null)
  const [localTier, setLocalTier] = useState<number | null>(null)

  // ---- helpers --------------------------------------------------------------

  const note = (text: string) => setMsg(text)
  const clearNoteSoon = () => setTimeout(() => setMsg(''), 2500)

  const fetchLocalState = async () => {
    if (!address || !appId) return
    setBusy('refresh')
    setMsg('Reading local state…')
    try {
      // GET /v2/accounts/{addr}/applications/{app-id}
      const info = await algod.accountApplicationInformation(address, appId).do()

      // Shape: { 'app-local-state': { 'key-value': [{ key, value: { bytes, uint, type }}, ...] } }
      const kv: Array<{ key: string; value: { bytes: string; uint: number; type: number } }> =
        info?.['app-local-state']?.['key-value'] ?? []

      const readUint = (lookupKey: string): number | null => {
        for (const item of kv) {
          // Keys are base64-encoded byte strings; decode to ASCII
          const decoded = typeof atob === 'function' ? atob(item.key) : ''
          if (decoded === lookupKey) return Number(item.value?.uint ?? 0)
        }
        return null
      }

      setLocalPts(readUint('pts'))
      setLocalTier(readUint('tier'))
      setMsg('Local state refreshed ✓')
    } catch (e: any) {
      console.error(e)
      setMsg(e?.message || 'Failed to read local state')
    } finally {
      setBusy(undefined)
      clearNoteSoon()
    }
  }

  const getSp = async (flat = false, fee = 1000) => {
    const sp = await algod.getTransactionParams().do()
    if (flat) {
      sp.flatFee = true
      // algosdk expects a *number* of microAlgos here (NOT BigInt)
      sp.fee = fee
    }
    return sp
  }

  // ---- actions --------------------------------------------------------------

  const optin = async () => {
    try {
      if (!address) throw new Error('Connect wallet')
      if (!appId || appId <= 0) throw new Error('Provide a valid App ID')

      setBusy('optin')
      note('Submitting opt-in…')

      const sp = await getSp()
      const txn = algosdk.makeApplicationOptInTxnFromObject({
        sender: address,
        appIndex: appId,
        suggestedParams: sp,
      })

      await signAndSend(pera, address, [txn], algod)
      note('Opt-in submitted ✓')
      await fetchLocalState()
    } catch (e: any) {
      console.error(e)
      note(e?.message || String(e))
    } finally {
      setBusy(undefined)
      clearNoteSoon()
    }
  }

  const claim = async () => {
    try {
      if (!address) throw new Error('Connect wallet')
      if (!appId || appId <= 0) throw new Error('Provide a valid App ID')
      if (threshold < 0) throw new Error('Threshold must be ≥ 0')

      setBusy('claim')
      note('Submitting claim…')

      const sp = await getSp()
      const appArgs = [
        new TextEncoder().encode('claim_tier'),
        algosdk.encodeUint64(threshold),
      ]

      const txn = algosdk.makeApplicationNoOpTxnFromObject({
        sender: address,
        appIndex: appId,
        suggestedParams: sp,
        appArgs,
      })

      await signAndSend(pera, address, [txn], algod)
      note('Claim submitted ✓')
      await fetchLocalState()
    } catch (e: any) {
      console.error(e)
      note(e?.message || String(e))
    } finally {
      setBusy(undefined)
      clearNoteSoon()
    }
  }

  const addPoints = async () => {
    try {
      if (!address) throw new Error('Connect wallet')
      if (!isAdmin) throw new Error('Connect the admin wallet to add points')
      if (!appId || appId <= 0) throw new Error('Provide a valid App ID')
      if (points <= 0) throw new Error('Points must be > 0')

      // target defaults to self if none provided
      const target = (targetAddr || address).trim()

      // Basic sanity check
      if (!algosdk.isValidAddress(target)) {
        throw new Error('Target address is not a valid Algorand address')
      }

      setBusy('add')
      note('Submitting add_points…')

      // Use flat fee for deterministic cost (adjust as your contract needs)
      const sp = await getSp(true, 1000)
      const appArgs = [
        new TextEncoder().encode('add_points'),
        algosdk.encodeUint64(points),
      ]

      // accounts[0] in this list becomes Txn.accounts[1] in TEAL.
      const txn = algosdk.makeApplicationNoOpTxnFromObject({
        sender: address, // admin
        appIndex: appId,
        suggestedParams: sp,
        appArgs,
        accounts: [target],
      })

      await signAndSend(pera, address, [txn], algod)
      note('Points submitted ✓')
      // If we updated self, refresh local state
      if (target === address) await fetchLocalState()
    } catch (e: any) {
      console.error(e)
      note(e?.message || String(e))
    } finally {
      setBusy(undefined)
      clearNoteSoon()
    }
  }

  // Auto-load local state when connected/app changes
  useEffect(() => {
    if (address && appId) {
      fetchLocalState()
    } else {
      setLocalPts(null)
      setLocalTier(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address, appId])

  // ---- UI -------------------------------------------------------------------

  return (
    <div className="card" aria-busy={!!busy}>
      {/* Top row: current on-chain local state */}
      <div
        style={{
          display: 'flex',
          gap: 16,
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <div style={{ fontSize: 13, opacity: 0.8 }}>
          <div>
            <strong>Local pts:</strong>{' '}
            {localPts ?? <em style={{ opacity: 0.6 }}>—</em>}
          </div>
          <div>
            <strong>Local tier:</strong>{' '}
            {localTier ?? <em style={{ opacity: 0.6 }}>—</em>}
          </div>
        </div>
        <button onClick={fetchLocalState} disabled={!address || busy === 'refresh'}>
          {busy === 'refresh' ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* Inputs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
        <div>
          <label htmlFor="sf-app-id">Superfan App ID</label>
          <input
            id="sf-app-id"
            inputMode="numeric"
            value={appId || ''}
            onChange={(e) => setAppId(Number(e.target.value) || 0)}
          />
        </div>

        <div>
          <label htmlFor="sf-threshold">Tier Threshold</label>
          <input
            id="sf-threshold"
            inputMode="numeric"
            value={threshold || ''}
            onChange={(e) => setThreshold(Number(e.target.value) || 0)}
          />
        </div>

        <div>
          <label htmlFor="sf-points">Points to Add (admin)</label>
          <input
            id="sf-points"
            inputMode="numeric"
            value={points || ''}
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

      {/* Actions */}
      <div style={{ display: 'flex', gap: 12, marginTop: 16, flexWrap: 'wrap' }}>
        <button onClick={optin} disabled={!address || busy === 'optin'}>
          {busy === 'optin' ? 'Opting in…' : 'Opt-in'}
        </button>

        <button onClick={claim} disabled={!address || busy === 'claim'}>
          {busy === 'claim' ? 'Claiming…' : 'Claim Tier'}
        </button>

        <button
          onClick={addPoints}
          disabled={!address || !isAdmin || busy === 'add'}
          title={isAdmin ? '' : 'Connect the admin wallet to enable'}
        >
          {busy === 'add' ? 'Adding…' : 'Admin: Add Points'}
        </button>
      </div>

      {/* Inline status/toast */}
      {!!msg && (
        <div
          role="status"
          aria-live="polite"
          style={{
            marginTop: 12,
            fontSize: 12,
            padding: '8px 10px',
            borderRadius: 8,
            background: 'rgba(0,0,0,.04)',
          }}
        >
          {msg}
        </div>
      )}

      {/* Footnotes */}
      <p style={{ marginTop: 12, fontSize: 12, opacity: 0.7 }}>
        Demo only — fees/logic are conservative. Replace alerts with real toasts and
        derive admin from contract state in production.
      </p>
    </div>
  )
}
