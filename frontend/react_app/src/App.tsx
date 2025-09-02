// frontend/react_app/src/App.tsx
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2025 Joltkin LLC.

/**
 * App.tsx
 * -----------------------------------------------------------------------------
 * Top-level application shell for the demo web UI.
 *
 * Responsibilities:
 *  - Provide wallet context to all descendants (via <WalletProvider>).
 *  - Render a minimal header with connection controls.
 *  - Offer simple client-side tab switching between:
 *      • Ticket Buy/Resale flows
 *      • Superfan Pass flows
 *  - Display environment/usage guidance (TestNet-only demo).
 *
 * Non-goals:
 *  - Global routing (kept intentionally simple for hackathon demo).
 *  - Styling system choice (uses inline styles for zero-config portability).
 *
 * Accessibility notes:
 *  - Tabs are implemented as buttons with `aria-pressed` and `disabled` states
 *    for clear AT feedback. If we later expand to many tabs, consider
 *    WAI-ARIA `role="tablist"` / `role="tab"` semantics with roving tabindex.
 *
 * Performance notes:
 *  - Panels are lightweight and mounted/unmounted on tab switch. If we add
 *    heavy subtrees, consider lazy-loading with React.lazy/Suspense.
 */

import React, { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import { WalletProvider, ConnectButton } from './wallet'
import { useNetwork } from '@txnlab/use-wallet-react'

// Statically typed handle for the value injected in vite.config.ts
declare const __APP_VERSION__: string | undefined

// Lazy panels for quicker first paint
const BuyResalePanel = lazy(() => import('./components/BuyResalePanel'))
const SuperfanPanel = lazy(() => import('./components/SuperfanPanel'))

type TabKey = 'buy' | 'sf'
const TAB_STORAGE_KEY = 'ui.tab'

// --------- Small, focused UI atoms (inside Provider zone) ---------

function NetworkBadge() {
  const { activeNetwork } = useNetwork()
  const style: React.CSSProperties = {
    fontSize: 12,
    padding: '4px 8px',
    borderRadius: 999,
    border: '1px solid #ddd',
    background: '#f7f7f7',
  }
  return <span style={style} title="Active Algorand network">{activeNetwork}</span>
}

function NotTestnetRibbon() {
  const { activeNetwork } = useNetwork()

  if (activeNetwork?.toLowerCase() === 'testnet') return null
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        marginBottom: 12,
        padding: '8px 10px',
        borderRadius: 6,
        background: '#fff4e5',
        border: '1px solid #ffd8a8',
        color: '#7a4d00',
        fontSize: 13,
      }}
    >
      Heads up: this demo is intended for <strong>TestNet</strong>. You’re on{' '}
      <strong>{activeNetwork || 'unknown'}</strong>.
    </div>
  )
}

function HeaderBar() {
  return (
    <header
      style={{
        display: 'flex',
        gap: 16,
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: 16,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h2 style={{ margin: 0 }}>🎭🎶 Joltkin x Algorand</h2>
        <NetworkBadge />
      </div>
      <ConnectButton />
    </header>
  )
}

function FooterNote() {
  const version = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : undefined
  return (
    <footer style={{ marginTop: 24, opacity: 0.7, fontSize: 12 }}>
      Demo only — use TestNet. Configure values in <code>.env</code> (<code>VITE_*</code>).
      {version ? (
        <span style={{ marginLeft: 8, paddingLeft: 8, borderLeft: '1px solid #ddd' }}>
          v{version}
        </span>
      ) : null}
    </footer>
  )
}

// --------- Main App ---------

export default function App() {
  // Persisted tab (survives reloads)
  const initialTab: TabKey = useMemo(() => {
    const raw = (typeof localStorage !== 'undefined' && localStorage.getItem(TAB_STORAGE_KEY)) || ''
    return raw === 'sf' ? 'sf' : 'buy'
  }, [])
  const [tab, setTab] = useState<TabKey>(initialTab)

  useEffect(() => {
    try {
      localStorage.setItem(TAB_STORAGE_KEY, tab)
    } catch {
      // non-fatal (private mode, etc.)
    }
  }, [tab])

  return (
    <WalletProvider>
      <div style={{ maxWidth: 980, margin: '32px auto', padding: 16 }}>
        <HeaderBar />
        <NotTestnetRibbon />

        {/* Simple two-tab navigation (accessible buttons) */}
        <nav style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
          <button
            onClick={() => setTab('buy')}
            aria-pressed={tab === 'buy'}
            disabled={tab === 'buy'}
            style={{
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid #ddd',
              background: tab === 'buy' ? '#eee' : '#fafafa',
              cursor: tab === 'buy' ? 'default' : 'pointer',
            }}
          >
            Ticket: Buy / Resale
          </button>

          <button
            onClick={() => setTab('sf')}
            aria-pressed={tab === 'sf'}
            disabled={tab === 'sf'}
            style={{
              padding: '8px 12px',
              borderRadius: 8,
              border: '1px solid #ddd',
              background: tab === 'sf' ? '#eee' : '#fafafa',
              cursor: tab === 'sf' ? 'default' : 'pointer',
            }}
          >
            Superfan Pass
          </button>
        </nav>

        {/* Panels are lazy to keep initial bundle small */}
        <main>
          <Suspense fallback={<div>Loading…</div>}>
            {tab === 'buy' ? <BuyResalePanel /> : <SuperfanPanel />}
          </Suspense>
        </main>

        <details style={{ marginTop: 16 }}>
          <summary style={{ cursor: 'pointer' }}>Environment & usage tips</summary>
          <div style={{ fontSize: 13, marginTop: 8, opacity: 0.85 }}>
            - Networks default to Nodely endpoints; you can point to a custom Algod later.<br />
            - Wallets can be added/removed in the wallet manager config.<br />
            - Use <code>VITE_SOURCEMAP=true</code> if you need production debugging (off by default).<br />
          </div>
        </details>

        <FooterNote />
      </div>
    </WalletProvider>
  )
}
