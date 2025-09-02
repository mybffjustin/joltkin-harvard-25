// frontend/react_app/src/main.tsx
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2025 Joltkin LLC.

/**
 * Application bootstrap entry for the React web client.
 *
 * Responsibilities:
 *  - Load browser polyfills before any other modules so downstream imports
 *    can rely on `Buffer`, `process`, etc. (Algorand SDK + wallet libs).
 *  - Create a React 18 root and mount the top-level <App/>.
 *  - Wrap the tree in <React.StrictMode> to surface unsafe lifecycles,
 *    legacy patterns, and unexpected side effects during development.
 *
 * Non-goals:
 *  - Global error handling / telemetry (handled in higher-level infra).
 *  - Server-side rendering (SSR) or hydration (CSR-only demo).
 *
 * Notes:
 *  - The non-null assertion (`!`) on `getElementById('root')` encodes the
 *    invariant that `index.html` must contain `<div id="root"></div>`.
 *    Consider an explicit runtime check if this file is reused outside Vite.
 */

import './polyfills'                 // Must be first: sets up Node globals in the browser.
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { WalletProvider } from '@txnlab/use-wallet-react'
import { manager } from './walletManager'

// Create a concurrent React root (React 18+). This enables concurrent features
// and better scheduling under StrictMode. For SSR/hydration use `hydrateRoot`.
ReactDOM.createRoot(document.getElementById('root')!).render(
  // StrictMode runs certain hooks/effects twice in dev to catch side effects.
  // This does not affect production builds.
  <React.StrictMode>
    <WalletProvider manager={manager}>
      <App />
    </WalletProvider>
  </React.StrictMode>
)


/**
 * Future hardening (non-functional):
 *  - Guard the root lookup:
 *      const el = document.getElementById('root');
 *      if (!el) throw new Error('Missing #root container');
 *  - Install an error boundary near the root and wire to telemetry.
 *  - Add web vitals reporting (e.g., `reportWebVitals`) if needed.
 *  - If migrating to SSR, replace `createRoot(...).render(...)` with
 *    `hydrateRoot(container, <App />)` and ensure markup parity.
 */
