// frontend/react_app/src/wallet.tsx
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2025 Joltkin LLC.

/**
 * Lightweight Pera Wallet integration for React apps.
 *
 * Responsibilities:
 *  - Establish and maintain a Pera Wallet session (connect/reconnect/disconnect).
 *  - Expose the active account address and wallet methods via React context.
 *  - Provide a small, accessible <ConnectButton/> for quick demos.
 *
 * Non-goals:
 *  - Transaction composition or network calls (handled elsewhere).
 *  - Complex UI state (toasts, modals, retries). Keep this layer minimal.
 */

import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { PeraWalletConnect } from '@perawallet/connect'

/**
 * Value stored in React context for consumers of the wallet.
 * Keep this stable/minimal so it’s easy to mock in tests.
 */
type WalletCtx = {
  /** Active wallet address (if connected). */
  address?: string
  /** Establish a new session with Pera (opens wallet UI). */
  connect: () => Promise<void>
  /** Disconnect and clear the current session. */
  disconnect: () => Promise<void>
  /** Raw Pera connector instance for advanced callers. */
  pera: PeraWalletConnect
  /** True once we’ve attempted session restore (prevents UI flicker). */
  ready: boolean
}

/** Internal context object — created once per module. */
const Ctx = createContext<WalletCtx | null>(null)

/** Utility to shorten Algorand addresses for display-only purposes. */
const shortAddress = (addr: string) => `${addr.slice(0, 6)}…${addr.slice(-4)}`

/**
 * WalletProvider
 *
 * Wrap your app in this provider to enable the `useWallet()` hook.
 * The provider:
 *  - Instantiates a single Pera connector.
 *  - Attempts to restore a previous session on mount (non-blocking).
 *  - Listens for `disconnect` events to keep UI in sync.
 */
export function WalletProvider({ children }: { children: ReactNode }) {
  // Create a single connector instance for the lifetime of this provider.
  // useMemo avoids re-instantiation on parent re-renders.
  const pera = useMemo(() => new PeraWalletConnect(), [])

  // Active account address returned by Pera. We only track the first account
  // for demo simplicity; callers that need multi-account can extend the context.
  const [address, setAddress] = useState<string>()
  // `ready` flips to true after we’ve attempted reconnection (success or fail).
  // This prevents ambiguous “connect” state in the UI.
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false

    // Attempt to reconnect if a prior session exists. This is safe to call
    // even when there is no session. It does not throw for “no session” cases.
    pera
      .reconnectSession()
      .then((accounts) => {
        if (!cancelled && accounts?.length) {
          setAddress(accounts[0])
        }
      })
      .catch(() => {
        // Swallow reconnect errors: absence of a session is not exceptional.
        // Network or wallet errors are user-actionable when they click Connect.
      })
      .finally(() => {
        if (!cancelled) setReady(true)
      })

    // Keep a stable reference to the event handler so we can remove it.
    const handleDisconnect = () => setAddress(undefined)

    // Some wallet connectors expose an EventEmitter-like API. Optional chain
    // guards here keep us resilient across minor SDK changes.
    pera.connector?.on?.('disconnect', handleDisconnect)

    // Cleanup on unmount: prevent setState on dead component and remove listener.
    return () => {
      cancelled = true
      // Remove disconnect listeners; SDK off() signature only takes the event name.
      pera.connector?.off?.('disconnect')
    }
  }, [pera])

  /**
   * Initiates a new connection with Pera.
   * Surfaces errors to caller so they can decide how to present them.
   */
  const connect = async () => {
    // Pera returns an array of account addresses on success.
    const accounts = await pera.connect()
    if (!accounts?.length) {
      throw new Error('No account returned by wallet')
    }
    setAddress(accounts[0])
  }

  /**
   * Closes the current Pera session and clears local state.
   * Safe to call when not connected.
   */
  const disconnect = async () => {
    await pera.disconnect()
    setAddress(undefined)
  }

  return (
    <Ctx.Provider value={{ address, connect, disconnect, pera, ready }}>
      {children}
    </Ctx.Provider>
  )
}

/**
 * Hook to access the current wallet context.
 * Throws if used outside of <WalletProvider/>, making failures loud/early.
 */
export function useWallet() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useWallet must be used within a <WalletProvider>')
  return v
}

/**
 * Minimal connect/disconnect button for demos.
 * - Disabled until the provider has completed session restore (`ready`).
 * - Shows a shortened address when connected.
 * - Keeps accessible labels/titles for screen readers and tooltips.
 */
export function ConnectButton() {
  const { address, connect, disconnect, ready } = useWallet()

  if (!ready) {
    return (
      <button disabled aria-busy="true" aria-live="polite">
        Loading wallet…
      </button>
    )
  }

  if (address) {
    const label = `Disconnect ${address}`
    return (
      <button
        title={address}
        aria-label={label}
        onClick={disconnect}
        // Don’t set disabled here: allow immediate user action.
      >
        Disconnect {shortAddress(address)}
      </button>
    )
  }

  return (
    <button onClick={connect} aria-label="Connect Pera Wallet">
      Connect Pera
    </button>
  )
}
