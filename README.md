<!-- README.md -->
# 🎭🎶 Joltkin X Algorand — Ticketing + Royalty Router + Superfan Pass

[![Network: TestNet](https://img.shields.io/badge/network-TestNet-blue)](#)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-informational)](#)
[![Algorand SDK](https://img.shields.io/badge/algosdk-v2%2Fv3-success)](#)
[![Streamlit](https://img.shields.io/badge/Streamlit-ready-brightgreen)](#)
[![Docker Compose](https://img.shields.io/badge/docker-compose-blue)](#)

- **Royalty Router (PyTeal)** — `buy()` splits primary revenue; `resale()` enforces an artist royalty.
- **Ticket ASA** — mint whole-number tickets (`decimals=0`, 1 unit = 1 ticket).
- **Superfan Pass (PyTeal)** — points + tiers (local state) for quests/loyalty.
- **Streamlit UI** — push-button end-to-end demo, including **print-ready QR packs**.
- **React + PeraWallet (optional)** — public web UX with real wallet signing.
- **CLI scripts** — preflight checks, deploy, and replayable flows.
- **Batteries-included Docker** — one command brings up React + Streamlit + backend tools.

> ⚠️ **TestNet demos only.** Audit & harden before any production use.

---

## Table of Contents

- [Overview](#overview)
- [TL;DR Quickstart (Local Dev)](#tldr-quickstart-local-dev)
- [Docker Quickstart (One Command)](#docker-quickstart-one-command)
- [Proof-of-Life (Works on My Machine)](#proof-of-life-works-on-my-machine)
- [System Architecture](#system-architecture)
- [Smart Contracts Design](#smart-contracts-design)
  - [Royalty Router](#royalty-router-backendcontractsrouterpy)
  - [Superfan Pass](#superfan-pass-backendcontractssuperfan_passpy)
- [Transaction Flows (Sequence)](#transaction-flows-sequence)
- [Streamlit Demo (What to Click)](#streamlit-demo-what-to-click)
- [QR Print Packs (Houses, Dorms, Referrals)](#qr-print-packs-houses-dorms-referrals)
- [Environment & Configuration](#environment--configuration)
- [Frontend Architecture](#frontend-architecture)
- [Preflight & CLI Examples](#preflight--cli-examples)
- [Troubleshooting](#troubleshooting)
- [Security & Production Hardening](#security--production-hardening)
- [Roadmap](#roadmap)
- [Repo Map](#repo-map)
- [License](#license)

---

## Overview

Think of this as a **digital box office** with a built-in accountant and fan club:

- **Ticket ASA** = your ticket stock (1 token = 1 seat).
- **Royalty Router** = the accountant that enforces splits + resale royalty.
- **Superfan Pass** = the punch card (points → tiers → perks).

Runs on **Algorand** (fast, low fee). A **Streamlit** app gives a no-code demo; an optional **React** frontend shows a production-style wallet flow.

**Everyday analogies**

- **Blockchain** → shared receipt book
- **Smart contract** → vending machine (inputs → deterministic outputs)
- **Router** → box-office accountant
- **Superfan Pass** → coffee-shop punch card
- **Wallet (Pera)** → your digital pocket

---

- Demo Video(docs/joltkin-video.mp4)
- Deploy Router(docs/1.png)
- Buy/Resale(docs/2.png)

---
## TL;DR Quickstart (Local Dev)

```bash
# 0) Python env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) Configure TestNet keys (repo root)
cp env.example .env
# fill: ALGOD_URL (Algonode works w/ blank token), INDEXER_URL, and mnemonics:
# CREATOR_MNEMONIC / SELLER_MNEMONIC / BUYER_MNEMONIC / ADMIN_MNEMONIC

# 2) Create ticket ASA (whole-number tickets)
python backend/scripts/create_ticket_asa.py --unit TIX --name "TDM Ticket" --total 1000 --decimals 0

# 3) Deploy Router (primary splits + resale royalty)
python backend/scripts/deploy_router.py \
  --artist <P1_ADDR> --p2 <P2_ADDR> --p3 <P3_ADDR> \
  --bps1 7000 --bps2 2500 --bps3 500 \
  --roy_bps 500 \
  --asa <ASA_ID> \
  --seller <PRIMARY_SELLER_ADDR>

# (optional) Prefund the router to cover inner-tx fees (MBR cushion)
python backend/scripts/common.py fund-app --appid <APP_ID> --amount 700000

# 4) Launch the demo UI (Streamlit)
streamlit run frontend/streamlit_app/app.py
````

**Optional: React web UI (local dev)**

```bash
cd frontend/react_app
cp .env.example .env      # set VITE_* values
npm i
npm run dev               # http://localhost:5173
```

---

## Docker Quickstart (One Command)

Everything is dockerized: **React (Vite → NGINX)**, **Streamlit**, and **backend CLI tools**.

```bash
# 1) From repo root, create your env
cp env.example .env
# Fill in TestNet mnemonics + (optional) INDEXER_URL/FRONTEND_BASE_URL

# 2) Bring up the stack
cd infra_devops/docker
docker compose up -d --build

# 3) Open UIs
# React (served by nginx):   http://localhost:5173
# Streamlit operator UI:     http://localhost:8501

# 4) Tail logs (optional)
docker compose logs -f --tail=100
```

To run a one-off backend script **inside** the backend container:

```bash
# Example: list created apps
docker compose run --rm backend python list_apps.py --details

# Example: preflight check
docker compose run --rm backend python check_state.py --mode buy --app <APP_ID> --asa <ASA_ID> --price 1000000
```

---

## Proof-of-Life (Works on My Machine)

Verify algod connectivity and balances before touching contracts:

```bash
# 1) Ping algod
python - <<'PY'
from algosdk.v2client import algod
import os
c = algod.AlgodClient(os.getenv("ALGOD_TOKEN",""), os.getenv("ALGOD_URL","https://testnet-api.algonode.cloud"))
print("status:", c.status())
PY

# 2) Check balances for your .env mnemonics
python - <<'PY'
import os
from algosdk import mnemonic, account
from algosdk.v2client import algod

def addr(m):
    return account.address_from_private_key(mnemonic.to_private_key(m))

c = algod.AlgodClient(os.getenv("ALGOD_TOKEN",""), os.getenv("ALGOD_URL","https://testnet-api.algonode.cloud"))
for label in ["CREATOR","SELLER","BUYER","ADMIN"]:
    mn = os.getenv(f"{label}_MNEMONIC")
    if not mn:
        continue
    a = addr(mn)
    bal = c.account_info(a)["amount"]
    print(f"{label:<7}", a, f"{bal/1e6:.3f} ALGO")
PY
```

---

## System Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│  React Frontend (Vite → NGINX)                                            │
│  • Public QR pages (/mint, /stamp, /staff.html)                           │
└───────────────▲───────────────────────────────────────────────────────────┘
                │ deep links
┌───────────────┴───────────────────────────────────────────────────────────┐
│  Streamlit Operator Console                                               │
│  • QuickStart → (Mint ASA → Deploy Router → Opt-ins → Prefund)            │
│  • Buy/Resale; Superfan points; QR packs; leaderboards                    │
└───────────────▲───────────────────────────────────────────────────────────┘
                │ Algod / Indexer (TestNet)
┌───────────────┴───────────────────────────────────────────────────────────┐
│  Algorand TestNet: Router App • Superfan App • Ticket ASA                 │
└───────────────────────────────────────────────────────────────────────────┘
```

**Separation of concerns**

* **ASA (tickets)**: `decimals=0` fungible asset. Ownership = ticket count.
* **Router app**: escrow-less coordinator:

  * reads splits (p1/p2/p3 + bps), royalty bps, asa id
  * validates a 3-txn atomic group
  * issues inner payments (primary split) or (royalty + seller payout) on resale
* **Superfan app**: local `points` and `tier`, admin-gated points updates.

---

## Smart Contracts Design

### Royalty Router (`backend/contracts/router.py`)

**Global state**

* `p1, p2, p3` (bytes): payout addresses
* `bps1, bps2, bps3` (uint): basis points, sum = 10000
* `roy_bps` (uint): resale artist royalty
* `asa` (uint): ticket ASA id
* `seller` (bytes): primary seller (for `buy()`)

**Schema**: Global `5 uints, 4 bytes`; Local `0/0`.

**Entry points**

* `buy()` — group must be:

  1. `ApplicationCall` (sender = buyer, args = `["buy"]`, `accounts=[p1,p2,p3,seller]`)
  2. `Payment` (buyer → app) `amt = price`
  3. `AssetTransfer` (seller → buyer) `amt = 1`, `index = asa`
     → inner payments: `price * bps{i}/10000` to `p{i}`

* `resale()` — group must be:

  1. `ApplicationCall` (sender = new buyer, args = `["resale"]`, `accounts=[p1,p2,p3,holder]`)
  2. `Payment` (new buyer → app) `amt = price`
  3. `AssetTransfer` (holder → new buyer) `amt = 1`, `index = asa`
     → inner payments: `price * roy_bps/10000` to `p1`, remainder to `holder`

**Fees**: AppCall should be **flat fee** and cover inner-txns (\~4\_000 µAlgos typical).
**Accounts array**: TEAL `accounts` max length = 4 → pass *only* required addresses.

### Superfan Pass (`backend/contracts/superfan_pass.py`)

* **Global**: `admin` (bytes)
* **Local**: `points` (uint), `tier` (uint)

**Entry points**

* `optin` — init local state
* `add_points(amount, account)` — **admin-only**, increases `points` for `accounts[0]`
* `claim_tier(threshold)` — user sets `tier` if `points >= threshold`

---

## Transaction Flows (Sequence)

### Primary Buy

```
Buyer                Router App                    Seller
  | 1) AppCall "buy"  |                               |
  |------------------>|                               |
  | 2) Pay price ---->|                               |
  |                   | itxn: split p1/p2/p3          |--> p1/p2/p3
  | 3) ASA 1 unit <-----------------------------------|
  |<------------------ confirmation ------------------|
```

### Resale

```
NewBuyer             Router App                    Holder
  | 1) AppCall "resale"                              |
  |------------------>|                              |
  | 2) Pay price ---->|                              |
  |                   | itxn: royalty to p1          |--> p1
  |                   | itxn: remainder to holder    |--> holder
  | 3) ASA 1 unit <----------------------------------|
  |<------------------ confirmation -----------------|
```

---

## Streamlit Demo (What to Click)

1. **Deploy Router** tab

   * “Create Demo Ticket ASA” → copy ASA id
   * “Deploy Router” → pass p1/p2/p3, splits, royalty, ASA
   * (Optional) “Setup: ASA → Opt-ins → Prefund App”
2. **Buy/Resale** tab

   * “Buyer Opt-in” → “Run Buy (1-click)”
   * (Optional) Resale panel: holder/new buyer flow
3. **Superfan Pass** tab

   * “Deploy Superfan (1-click)”
   * Buyer opt-in → Admin “Add Points” → Buyer “Claim Tier”
4. **HARVARD / Venue Partner** tabs

   * Generate **print-ready QR packs** (posters + sticker sheets)
   * Auto-cycling **Staff Screen** (Mint → Stamp → Leaderboard)

---

## QR Print Packs (Houses, Dorms, Referrals)

Exports a **ZIP** with:

* `posters.pdf` (1 big QR per page, optional logo)
* `stickers_letter.pdf` (3X5) and `stickers_a4.pdf` (3X8)
* `qrs/*.png` individual codes
* `MANIFEST.csv` with `utm_*` fields

Use for:

* **Houses** (Adams…Winthrop) and **First-Year Dorms** (Apley Court…Wigglesworth)
* **Section X House/Dorm** matrices
* **Referral** links (`?ref=alice&sf=<app_id>`)
* **Cast/Crew claim cards** (`/claim_card?name=...&role=...`)

> PDFs require `reportlab` + `pillow`. PNG QRs require `qrcode[pil]`.

---

## Environment & Configuration

### Python `.env` (repo root)

```ini
ALGOD_URL=https://testnet-api.algonode.cloud
ALGOD_TOKEN=                 # blank works for Algonode
CREATOR_MNEMONIC="...25 words..."
SELLER_MNEMONIC="..."
BUYER_MNEMONIC="..."
ADMIN_MNEMONIC="..."
INDEXER_URL=https://testnet-idx.algonode.cloud
INDEXER_TOKEN=
FRONTEND_BASE_URL=http://localhost:5173
```

### Frontend `frontend/react_app/.env`

```ini
VITE_ALGOD_URL=https://testnet-api.algonode.cloud
VITE_ALGOD_TOKEN=
VITE_ROUTER_APP_ID=0
VITE_TICKET_ASA_ID=0
VITE_SUPERFAN_APP_ID=0
VITE_SUPERFAN_ADMIN_ADDR=
```

> Docker builds can pass `VITE_*` args during image build (see compose).

---

## Frontend Architecture

* **React + Vite** (fast HMR)
* **PeraWalletConnect** for session/signing
* **algosdk** for tx building
* **Node polyfills** for browser (`buffer`, `process`, `global`) via `vite-plugin-node-polyfills`

**Signing helper** groups txns, base64-encodes for Pera, accepts returned blobs, submits to algod, and waits for confirmation.

---

## Preflight & CLI Examples

> Paths use `backend/scripts`.

Fund app for inner fees:

```bash
python backend/scripts/common.py fund-app --appid <APP_ID> --amount 1100000
```

Primary buy:

```bash
python backend/scripts/buy_ticket.py --app <APP_ID> --asa <ASA_ID> --price 1000000
```

Resale (holder → new buyer):

```bash
python backend/scripts/resale_via_router.py --app <APP_ID> --asa <ASA_ID> --price 1200000
```

Preflight (sanity checks):

```bash
python backend/scripts/check_state.py --mode buy    --app <APP_ID> --asa <ASA_ID> --price 1000000
python backend/scripts/check_state.py --mode resale --app <APP_ID> --asa <ASA_ID> --price 1200000
```

List apps:

```bash
python backend/scripts/list_apps.py --details
python backend/scripts/list_apps.py --address <ADDR> --details --json | jq .
```

---

## Troubleshooting

* **Vite: “global is not defined” / “buffer externalized”**
  Ensure `vite.config.ts` includes node polyfills and `src/polyfills.ts` sets globals.

* **`account ... balance below min` / `overspend`**
  Fund the account/app. Use `backend/scripts/common.py fund-app`.

* **`invalid ApplicationArgs index` / `unavailable Account ... itxn_field Receiver`**
  Wrong **group order** or missing `accounts`. Router expects **\[AppCall, Payment, ASA]** and `AppCall` at **index 0**.

* **Algod 400 Bad Request**
  Mis-grouped txns, wrong signer, or insufficient fee. Compare with `check_state.py` output.

* **Streamlit: duplicate element id**
  Always provide a unique `key=` (this repo uses `frontend/streamlit_app/ui/keys.py` and `k(page, name)`).

---

## Security & Production Hardening

* **Never** commit real mnemonics; TestNet only for this demo stack.
* Mount `.env` **read-only** (`:ro`) in containers.
* In contracts, enforce:

  * `bps1 + bps2 + bps3 == 10000`
  * ASA id validation; `amt == 1` transfers
  * AppCall fee ≥ cost of inner txns
* In production UX, split signing responsibilities (buyer vs seller/holder).
* Rate-limit UI; surface error codes from `pendingTransactionInformation`; monitor confirmations/failures.

---

## Roadmap

* Inventory (per seat/section) on-chain
* Time-bounded resale windows & caps
* Superfan quest templates (off-chain verifier → on-chain points)
* Backoffice for split/royalty config
* Multi-asset/event support

---

## Repo Map

```
backend/
  contracts/
    router.py                 # PyTeal royalty router: buy/resale; splits + resale royalty
    superfan_pass.py          # PyTeal superfan app: points & tier (local state)
  scripts/
    buy_ticket.py             # CLI: primary buy atomic group [AppCall, Pay, ASA]
    check_state.py            # Preflight: MBR, balances, opt-ins, app prefund
    codegen.py                # Dev helper: generate TestNet mnemonics -> .env
    common.py                 # Shared utils: algod client, fund_app(), helpers
    create_ticket_asa.py      # Mint ticket ASA (decimals=0; 1 unit = 1 ticket)
    deploy_router.py          # Compile + deploy Router; prints app_id/address
    deploy_superfan.py        # Compile + deploy Superfan; prints app_id/address
    fund.py                   # Simple account/app funding helpers (µAlgos)
    list_apps.py              # List creator apps; pretty-print global state
    quest_ops.py              # Superfan ops: opt-in, add_points, claim_tier
    resale_via_router.py      # CLI: resale atomic group via Router

frontend/
  react_app/                  # Public QR UX + wallet flow (Vite → NGINX)
    Dockerfile                # Multi-stage build; serve dist/ via NGINX (:80)
    nginx.conf                # SPA hosting, caching, healthcheck
    index.html                # Vite entry HTML (dev/build)
    package.json              # Scripts + deps (react, viem, pera, polyfills)
    tsconfig.json             # TS compiler opts (strict)
    tsconfig.node.json        # TS for node-side tooling (Vite)
    vite.config.ts            # Vite config + node polyfills (buffer/process/global)
    public/
      manifest.webmanifest    # PWA manifest (name/icons/theme)
      staff.html              # Standalone staff/leaderboard screen (auto-rotate)
    src/
      App.tsx                 # App shell & route logic for QR pages
      main.tsx                # Vite bootstrap; mounts <App />
      polyfills.ts            # Sets browser globals: Buffer/process/global
      wallet.tsx              # Pera wallet connect UI; connect/disconnect
      walletManager.ts        # Session mgmt; sign/group tx utils; submit/wait
      components/             # Reusable UI (QR renderer, buttons, toasts, etc.)
      lib/                    # Pure helpers (query parsing, UTM, formatting)
      shims/                  # Type shims for polyfilled modules
      wc/                     # Web components (if any; lightweight statics)
    dist/                     # Build output (generated; served by NGINX)
      index.html              # Built SPA entry
      manifest.webmanifest    # Copied from /public
      staff.html              # Built staff screen
      assets/                 # Hashed JS/CSS/img chunks (auto-generated)
    README.md                 # Frontend-specific notes (dev tips, env)
  streamlit_app/              # Operator Console (on-site/hackathon ops)
    Dockerfile                # Hardened Python image; non-root; healthcheck
    README.md                 # Operator-focused docs (tabs, flows)
    app.py                    # Main UI: tabs wiring + page render calls
    core/
      __init__.py
      clients.py              # Algod/Indexer clients; memoized access
      config.py               # Env loader (dotenv) and settings object
      constants.py            # Fees, MBRs, TEAL params, defaults
      state.py                # Session state helpers/presets
    pages/
      __init__.py
      deploy_router.py        # Create ASA; deploy Router; opt-ins; prefund
      trade.py                # Buy/Resale flows + opt-in helpers (unique keys)
      superfan.py             # Deploy; add points; claim tier; leaderboard
      harvard_partner.py         # Print packs (posters/stickers); dorm/house tools
      venue_partner.py       # Venue QR flows + staff link generator
      tools.py                # Checklists, deep-link builders, misc utils
    services/
      __init__.py
      algorand.py             # SDK wrappers: balances, read globals, opt-ins
      qrprint.py              # ZIP builder; PNG QRs; PDF posters/sheets
    ui/
      __init__.py
      components.py           # Shared Streamlit UI widgets
      keys.py                 # k(page,name) → stable widget keys (avoid dup IDs)
      layout.py               # Page config; stack-or-columns helper
      sidebar.py              # Accounts panel; presets import/export; env hints

infra_devops/
  docker/
    docker-compose.yml        # Orchestrates frontend, streamlit, backend (CLI)
  observability/              # (placeholder) metrics/logging/tracing configs

env.example                    # Copy to .env; TestNet endpoints + mnemonics
requirements.txt              # Python deps (algosdk, streamlit, qrcode/reportlab*)
pyproject.toml                # Formatting/linting/tools (black/ruff/etc.)
LICENSE                       # Apache-2.0
README.md                     # Root docs (this file)
```

---

## License

**Apache-2.0** © 2025 Joltkin LLC.
