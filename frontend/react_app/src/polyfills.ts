// frontend/react_app/src/polyfills.ts
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2025 Joltkin LLC.

/**
 * Minimal browser polyfills for libraries that expect Node-like globals.
 *
 * Responsibilities:
 *  - Provide `Buffer`, `process`, and `global` on `globalThis` for SDKs (e.g., algosdk)
 *    and crypto libs that were authored with Node in mind.
 *  - Be safe to import in any browser context and a no-op if globals already exist.
 *
 * Non-goals:
 *  - Full Node.js API surface (fs, net, crypto randomness beyond Web Crypto, etc.).
 *  - Polyfilling features already available in evergreen browsers.
 *
 * Usage:
 *  - Import this module **before** any package that assumes Node globals:
 *      import './polyfills'
 *      // then other imports that rely on Buffer/process/global
 *
 * Notes:
 *  - We intentionally avoid reconfiguring existing globals to reduce the chance of
 *    breaking other tooling. We only define them if absent.
 *  - In TypeScript projects *without* `@types/node`, we provide minimal ambient
 *    declarations so `import process from 'process'` type-checks.
 */

// --------------------------------------------------------------------------------------
// Type-only shims for projects that do not include @types/node.
// These keep TS happy when using the 'process' npm package’s default export in the browser.
// If @types/node is added later, these will merge/augment without conflict.
// --------------------------------------------------------------------------------------

type ProcessLike = {
  env: Record<string, string | undefined>
  nextTick: (callback: (...args: any[]) => void, ...args: any[]) => void
  browser?: boolean
}

// Minimal module declaration so TS accepts `import process from 'process'` without @types/node.
declare module 'process' {
  const _default: ProcessLike
  export default _default
}

// --------------------------------------------------------------------------------------
// Runtime polyfills
// --------------------------------------------------------------------------------------

import { Buffer } from 'buffer'
import process from 'process'

// Use `globalThis` so this works in window, worker, and other JS realms.
// (In browsers, `globalThis === window`.)
const g = globalThis as unknown as {
  Buffer?: typeof Buffer
  process?: ProcessLike
  global?: unknown
}

/**
 * Polyfill Buffer:
 * - Only define if not present to avoid clobbering.
 * - Many crypto/encoding utilities expect `globalThis.Buffer`.
 */
if (typeof g.Buffer === 'undefined') {
  // @ts-expect-error: augmenting the global object for Node-compat in the browser
  g.Buffer = Buffer
}

/**
 * Polyfill process:
 * - Provide a minimal `process` object with `env` and `nextTick`.
 * - Some libs check `process.browser === true` in bundler targets; set it.
 */
if (typeof g.process === 'undefined') {
  // Start from the imported shim but ensure required fields exist.
  const proc: ProcessLike = process as ProcessLike

  // Ensure `env` exists to avoid `undefined` access in config-driven libs.
  proc.env = proc.env ?? {}

  // Provide `nextTick` using microtask queue if missing (Safari/WebView safety).
  proc.nextTick =
    proc.nextTick ??
    ((cb: (...args: any[]) => void, ...args: any[]) =>
      Promise.resolve().then(() => cb(...args)))

  // Mark as a browser runtime for libraries that branch on this flag.
  proc.browser = true

  // @ts-expect-error: augmenting the global object for Node-compat in the browser
  g.process = proc
}

/**
 * Polyfill global:
 * - Some legacy libs (e.g., bn.js, older buffers) reference `global` instead of `globalThis`.
 * - Point it at the platform-global object.
 */
if (typeof g.global === 'undefined') {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(g as any).global = g
}

// --------------------------------------------------------------------------------------
// End of polyfills. Intentionally no exports.
// --------------------------------------------------------------------------------------
