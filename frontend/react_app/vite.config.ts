// frontend/react_app/vite.config.ts
// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2025 Joltkin LLC.
//
// Vite configuration for a React + TypeScript single-page app that talks to Algorand.
//
// Design goals:
//  - First-class DX (fast dev server, React Fast Refresh).
//  - Browser build that tolerates Node-ish globals some deps assume (Buffer/process/global).
//  - Minimal surface area: keep defaults unless there’s a clear reason to change.
//  - Safe-by-default production settings (no unnecessary sourcemaps).
//
// Notes:
//  • We do NOT bring @types/node into the *app*; only the config file gets Node types via tsconfig.node.json.
//  • We map `global` → `globalThis` and stub `process.env` to `{}` for libs that probe it.
//    Real runtime config comes from `import.meta.env.VITE_*`, not from `process.env`.

import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { nodePolyfills } from 'vite-plugin-node-polyfills'

// Optional: bundle visualizer (only enabled when VITE_ANALYZE=true)
import { visualizer } from 'rollup-plugin-visualizer'

// Tiny empty shim to avoid vm-browserify pulling `eval`
const VM_EMPTY_ALIAS = '/src/shims/empty.ts'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '') // read all, we only use VITE_*

  const base = env.VITE_BASE ?? '/'
  const devPort = Number(env.VITE_PORT ?? 5173)
  const previewPort = Number(env.VITE_PREVIEW_PORT ?? 4173)
  const sourcemap = env.VITE_SOURCEMAP === 'true'
  const chunkLimitKb = Number(env.VITE_CHUNK_LIMIT_KB ?? 700)
  const analyze = env.VITE_ANALYZE === 'true'

  return {
    // Only expose VITE_* to the client
    envPrefix: 'VITE_',

    base,

    plugins: [
      react(),
      nodePolyfills({
        protocolImports: true,
      }),
      // turn on with: VITE_ANALYZE=true npm run build
      analyze &&
        (visualizer({
          filename: 'dist/stats.html',
          gzipSize: true,
          brotliSize: true,
          open: false,
        }) as any),
    ].filter(Boolean),

    publicDir: 'public',

    define: {
      global: 'globalThis',
      'process.env': {}, // DO NOT put secrets here
      __APP_VERSION__: JSON.stringify(process.env.npm_package_version ?? '0.0.0'),
    },

    // Keep polyfills consistently available in dev pre-bundle
    optimizeDeps: {
      include: ['buffer', 'process'],
    },

    // Avoid vm-browserify (triggers eval & CSP issues)
    resolve: {
      alias: {
        vm: VM_EMPTY_ALIAS,
      },
    },

    server: {
      host: true,
      port: devPort,
    },

    preview: {
      host: true,
      port: previewPort,
    },

    build: {
      target: 'es2024',
      sourcemap,
      chunkSizeWarningLimit: chunkLimitKb,
      rollupOptions: {
        output: {
          // Keep big deps out of your main chunk
          manualChunks: {
            react: ['react', 'react-dom'],
            algo: ['algosdk'],
            // If/when you add wallet libs that are heavy, keep them here:
            // wallet: ['@txnlab/use-wallet', '@walletconnect/sign-client', '@walletconnect/modal']
          },
        },
      },
    },

    esbuild: {
      legalComments: 'none',
    },
  }
})
