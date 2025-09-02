<!-- frontend/react_app/README.md -->

# Joltkin X Algorand — React/TypeScript Frontend (Pera Wallet)

Minimal **Vite + React + TypeScript** dApp that drives the Python/PyTeal stack:

* **Royalty Router** — primary `buy` (split to p1/p2/p3) and `resale` (artist royalty).
* **Superfan Pass** — user `opt-in`, `claim_tier`; admin `add_points`.

**Wallet:** [`@perawallet/connect`](https://github.com/perawallet/connect).
**Network:** Algorand **TestNet** (Algonode by default).
**Build:** Vite → static assets → **NGINX** container for production.

> ⚠️ **Demo signing**: real buy/resale needs **two signers** (buyer + seller/holder).
> This starter signs the whole group with the **connected account** for speed. Use it for demos, not production multi-party settlement.

## Quickstart (Local Dev)

```bash
# From repo root or frontend/react_app
cd frontend/react_app

# 1) Install deps
npm ci  # or: npm i

# 2) Configure env
cp .env.sample .env  # then fill the IDs/addresses below

# 3) Run dev server
npm run dev          # http://localhost:5173
```

Open [http://localhost:5173](http://localhost:5173)

## Configuration

Create `frontend/react_app/.env` (values are compiled at build time by Vite):

```ini
# Algod endpoint (Algonode TestNet works with empty token)
VITE_ALGOD_URL=https://testnet-api.algonode.cloud
VITE_ALGOD_TOKEN=
VITE_NETWORK=TestNet

# Router (royalty) app + ticket ASA (from Python deploy scripts)
VITE_ROUTER_APP_ID=0
VITE_TICKET_ASA_ID=0

# (Optional) Superfan app config
VITE_SUPERFAN_APP_ID=0
VITE_SUPERFAN_ADMIN_ADDR=
```

### Notes

* Vite envs are **compile-time**. Changing `.env` requires a rebuild.
* For campus/public scans, serve the site from a **public URL** and update any QR generators accordingly.

## What’s Included

* `src/wallet.tsx` — connect/disconnect with Pera; basic session handling.
* `src/lib/algorand.ts` — algod client, helpers, **group build + sign + send**.
* `src/components/BuyResalePanel.tsx` — constructs `[AppCall, Pay, ASA]` groups.
* `src/components/SuperfanPanel.tsx` — opt-in, claim tier, admin add-points.
* `src/App.tsx` — minimal tabbed UI.
* `vite.config.ts` — includes **node polyfills** (buffer/process/global) for browser libs.
* `public/` — static assets; SPA fallback handled in `nginx.conf`.

## Scripts

```bash
npm run dev       # Vite dev server with HMR (port 5173)
npm run build     # Production build -> dist/
npm run preview   # Preview local static server (not NGINX)
```

## Docker (Production Image)

This project ships a **multi-stage** Dockerfile that builds with Vite and serves via **NGINX**.

Build from repo root (Dockerfile assumes repo-root context):

```bash
docker build \
  -f frontend/react_app/Dockerfile \
  -t joltkin-frontend \
  --build-arg VITE_ALGOD_URL=https://testnet-api.algonode.cloud \
  --build-arg VITE_ALGOD_TOKEN= \
  --build-arg VITE_NETWORK=TestNet \
  --build-arg VITE_ROUTER_APP_ID=0 \
  --build-arg VITE_TICKET_ASA_ID=0 \
  --build-arg VITE_SUPERFAN_APP_ID=0 \
  --build-arg VITE_SUPERFAN_ADMIN_ADDR= \
  .
```

Run:

```bash
docker run --rm -p 5173:80 joltkin-frontend
# Open http://localhost:5173
```

### Compose

Use the repo’s `infra_devops/docker/docker-compose.yml`:

```bash
cd infra_devops/docker
docker compose up --build
```

This exposes:

* Frontend at `http://localhost:5173`
* Streamlit at `http://localhost:8501` (if enabled)

## Multi-Signer Reality Check (Production)

For **Primary Buy**:

* Buyer signs: `AppCall(buy)`, `Payment(buyer→app)`
* Seller signs: `AssetTransfer(seller→buyer, amt=1, index=ASA)`

For **Resale**:

* New buyer signs: `AppCall(resale)`, `Payment(newbuyer→app)`
* Holder signs: `AssetTransfer(holder→newbuyer, amt=1)`

### Action items for prod UX

* Implement a **two-step signing flow** (request → share → finalize) or leverage a **clawback/escrow** design to avoid live seller signature.
* Validate **MBR**, **opt-ins**, and **fees** before building the group.
* Perform a **simulation**/preflight (dry-run or indexer/state checks) and surface errors clearly.

## Troubleshooting

* **`global is not defined` / `buffer is not defined`**
  Ensure `vite.config.ts` includes node polyfills and the app imports `buffer/process` where needed. Clear Vite cache and rebuild.

* **Pera stuck connecting / stale session**
  Disconnect in UI, clear localStorage for the site, or close/reopen Pera mobile session. Reconnect.

* **CORS or 400 Bad Request from algod**
  Check ALGOD\_URL/TOKEN; use Algonode TestNet with empty token or your own node. Validate group order and signers.

* **`invalid ApplicationArgs index` / `unavailable Account ... itxn_field`**
  Group is mis-ordered or `accounts` missing. Router expects **\[AppCall, Payment, ASA]**, with `AppCall` at **index 0**, and `accounts=[p1,p2,p3,seller|holder]`.

* **Wrong IDs after redeploy**
  Vite embeds env at build time. Update `.env` and rebuild (or pass `--build-arg` in Docker).

## Security & Hardening

* Add a **Content-Security-Policy** in `nginx.conf` (block inline eval, third-party origins).
* Turn on **Subresource Integrity** (SRI) for external `<script>`/`<link>` if used.
* Avoid logging sensitive data (mnemonics/addresses).
  *Never* handle mnemonics in the browser; use wallet providers.
* Monitor **pendingTransactionInformation** errors and backoff/retry on transient network issues.

## Project Layout (Frontend)

```bash
frontend/
  react_app/
    Dockerfile       # build + NGINX serve
    nginx.conf       # SPA fallback; caching headers
    index.html       # Vite entry
    package.json
    public/          # static assets (served as-is)
    src/
      App.tsx
      components/
        BuyResalePanel.tsx
        SuperfanPanel.tsx
      lib/
        algorand.ts
      wallet.tsx
    tsconfig.json
    vite.config.ts
```

## Notes for Integrators

* QR generators in the Streamlit app assume the frontend is available at a stable base URL (often `:5173`).
  If you deploy behind a different domain/port, regenerate QRs or set redirects.
* If you need **runtime** config without rebuilds, serve a `config.json` from `/public` and fetch it on app boot;
  prefer this for environment-specific deployment knobs.
