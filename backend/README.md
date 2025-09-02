<!-- backend/README.md -->
# Joltkin X Algorand — Backend

Smart contracts (PyTeal) and CLI scripts for **Ticketing + Royalty Router + Superfan Pass** on **Algorand TestNet**.

- Contracts live in `backend/contracts/`
- Scripts to deploy/run flows in `backend/scripts/`
- Optional Docker image to run scripts in a clean environment

> ⚠️ **TestNet only.** These tools accept mnemonics for speed. Do **not** use production secrets here.

---

## Table of Contents

- [Architecture](#architecture)
- [Local Setup](#local-setup)
- [Docker Usage](#docker-usage)
- [CLI Cookbook](#cli-cookbook)
- [Preflight & Sanity Checks](#preflight--sanity-checks)
- [Transaction Groups](#transaction-groups)
- [Fee Model & MBR](#fee-model--mbr)
- [State Schema](#state-schema)
- [Security Notes](#security-notes)
- [Troubleshooting](#troubleshooting)
- [Directory Map](#directory-map)
- [License](#license)

---

## Architecture

```markdown

Algorand TestNet
├─ ASA (tickets: decimals=0)
├─ Router App (splits + resale royalty)
└─ Superfan App (points + tier per user)

````markdown

- **Router App** verifies a 3-txn atomic group and executes inner payments:
  - Primary: split revenue to p1/p2/p3
  - Resale: pay artist royalty, remainder to holder
- **Superfan App** tracks `points` and `tier` in **local state**; admin can award points.

---

## Contracts

### Royalty Router

**File:** `contracts/router.py` (PyTeal)

**Purpose:** Enforce primary splits and resale royalty for ticket resales.

**Globals**

- `p1, p2, p3` *(bytes)* — payout addresses
- `bps1, bps2, bps3` *(uint)* — basis points; **sum must equal 10000**
- `roy_bps` *(uint)* — resale royalty bps (typically paid to `p1`)
- `asa` *(uint)* — ticket ASA id
- `seller` *(bytes)* — primary seller (used in `buy()`)

**Entry points**

- `buy()` — expects an atomic group:
  1. `ApplicationCall` (sender = **buyer**), `args=["buy"]`, `accounts=[p1,p2,p3,seller]`
  2. `Payment` (buyer → app), `amt = price`
  3. `AssetTransfer` (seller → buyer), `amt = 1`, `index = asa`
  - Inner txns: `price * bps{i}/10000` to `p{i}`

- `resale()` — expects:
  1. `ApplicationCall` (sender = **new buyer**), `args=["resale"]`, `accounts=[p1,p2,p3,holder]`
  2. `Payment` (new buyer → app), `amt = price`
  3. `AssetTransfer` (holder → new buyer), `amt = 1`, `index = asa`
  - Inner txns: `(price * roy_bps/10000)` to `p1`; remainder to `holder`

**Notes**

- AppCall should be **flat fee** and cover inner tx cost (see [Fee Model & MBR](#fee-model--mbr)).
- `accounts[]` length is limited—pass only required addresses in TEAL `accounts`.

---

### Superfan Pass

**File:** `contracts/superfan_pass.py` (PyTeal)

**Purpose:** Track loyalty points & tiers per user.

**Global**

- `admin` *(bytes)* — admin address

**Local**

- `points` *(uint)* — accumulated points
- `tier` *(uint)* — claimed tier

**Entry points**

- `optin` — initialize local state
- `add_points(amount, account)` — **admin-only**, increases `points` for `accounts[0]`
- `claim_tier(threshold)` — user sets `tier` if `points >= threshold`

---

## Environment

Contracts and scripts read `.env` in repo root:

```ini
ALGOD_URL=https://testnet-api.algonode.cloud
ALGOD_TOKEN=
INDEXER_URL=https://testnet-idx.algonode.cloud
INDEXER_TOKEN=
CREATOR_MNEMONIC="... 25 words ..."
SELLER_MNEMONIC="... 25 words ..."
BUYER_MNEMONIC="... 25 words ..."
ADMIN_MNEMONIC="... 25 words ..."
````

> Use **TestNet** accounts only. Fund via the Algonode TestNet dispenser.

---

## Local Setup

```bash
# From repo root
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp env.example .env
# edit .env with your TestNet mnemonics / endpoints
```

---

## Docker Usage

Build the backend tools image:

```bash
docker build -f backend/Dockerfile -t joltkin-backend .
```

Run a script inside the container:

```bash
docker run --rm -it \
  -v "$(pwd)/.env:/app/.env:ro" \
  joltkin-backend python scripts/list_apps.py --details
```

Or use **docker compose** (recommended, integrates with frontend & Streamlit):

```bash
cd infra_devops/docker
docker compose up --build -d
docker compose run --rm backend python scripts/check_state.py --mode buy --app <APP_ID> --asa <ASA_ID> --price 1000000
```

---

## CLI Cookbook

Mint a **Ticket ASA** (decimals=0; 1 unit = 1 ticket):

```bash
python backend/scripts/create_ticket_asa.py \
  --unit TIX --name "Demo Ticket" --total 1000 --decimals 0
```

Deploy **Superfan**:

```bash
python backend/scripts/deploy_superfan.py
# prints app_id and app address
```

Deploy **Router** (primary splits + resale royalty):

```bash
python backend/scripts/deploy_router.py \
  --artist <P1_ADDR> --p2 <P2_ADDR> --p3 <P3_ADDR> \
  --bps1 7000 --bps2 2500 --bps3 500 \
  --roy_bps 500 \
  --asa <ASA_ID> \
  --seller <PRIMARY_SELLER_ADDR>
```

Fund the **Router app account** for inner-tx fees (optional but recommended):

```bash
python backend/scripts/common.py fund-app --appid <APP_ID> --amount 700000
```

**Primary buy** (buyer ↔ seller via Router):

```bash
python backend/scripts/buy_ticket.py --app <APP_ID> --asa <ASA_ID> --price 1000000
```

**Resale** (holder ↔ new buyer via Router):

```bash
python backend/scripts/resale_via_router.py --app <APP_ID> --asa <ASA_ID> --price 1200000
```

List apps (creator):

```bash
python backend/scripts/list_apps.py --details
python backend/scripts/list_apps.py --address <ADDR> --details --json | jq .
```

---

## Preflight & Sanity Checks

Before running flows, validate balances/MBR/opt-ins:

```bash
python backend/scripts/check_state.py --mode buy    --app <APP_ID> --asa <ASA_ID> --price 1000000
python backend/scripts/check_state.py --mode resale --app <APP_ID> --asa <ASA_ID> --price 1200000
```

The script checks:

- Algo balance (accounts + app) and **Minimum Balance Requirement**
- Buyer/seller/holder **opt-in** to the ASA
- Router globals present (`p1/p2/p3/bps*/roy_bps/asa/seller`)
- AppCall fee sufficiency (estimated)

---

## Transaction Groups

### Primary buy

```markdown
[0] AppCall  (buyer, "buy", accounts=[p1,p2,p3,seller])
[1] Payment  (buyer → app, amt=price)
[2] AssetXfer(seller → buyer, index=asa, amt=1)
```

### Resale

```markdown
[0] AppCall  (new buyer, "resale", accounts=[p1,p2,p3,holder])
[1] Payment  (new buyer → app, amt=price)
[2] AssetXfer(holder → new buyer, index=asa, amt=1)
```

> The **order and indices** matter. The contract reads fields by index.

---

## Fee Model & MBR

- AppCall must be **flat fee** and cover inner transactions:

  - Typical Router inner txns: 2–4 payments → fee budget ≈ **3,000–4,000 µAlgos**
- Keep a small **MBR cushion** in the app account to avoid `overspend` on inner txns:

  - See `common.py fund-app` helper.

---

## State Schema

### Router

- Global: `5 uints, 4 bytes`

  - `bps1, bps2, bps3, roy_bps, asa` (uint)
  - `p1, p2, p3, seller` (bytes)
- Local: `0 / 0` (none)

### Superfan

- Global: `admin` (bytes)
- Local: `points, tier` (uint)

---

## Security Notes

- Do **not** ship real mnemonics. Use TestNet and **read-only** mounts for `.env`.
- Validate split math: `bps1 + bps2 + bps3 == 10000`
- **ASA checks**: enforce `index == asa` and `amt == 1` for ticket transfer
- Keep AppCall fees sufficient for inner tx cost; prefer **flat fee**
- In production, separate signers (buyer vs seller/holder) and use a robust wallet flow (e.g., multi-party signing UX)

---

## Troubleshooting

- **`invalid ApplicationArgs index` / `unavailable Account ... itxn_field Receiver`**
  Group order or `accounts[]` is wrong. Recheck the [Transaction Groups](#transaction-groups) section.

- **`account balance below min` / `overspend`**
  Top up accounts and/or fund the app address:
  `python backend/scripts/common.py fund-app --appid <APP_ID> --amount 700000`

- **Algod 400 Bad Request**
  Mis-grouped transactions, wrong signer, insufficient fee, or ASA not opted-in.

- **Indexer queries empty**
  Ensure your `INDEXER_URL` is reachable and you’re querying the correct app id / address.

---

## Directory Map

```text
backend/
  contracts/
    router.py             # Royalty router (buy/resale; splits + resale royalty)
    superfan_pass.py      # Superfan app (points & tier in local state)
  scripts/
    buy_ticket.py         # CLI: primary buy [AppCall, Pay, ASA]
    check_state.py        # Preflight: MBR, balances, opt-ins, globals
    codegen.py            # Generate sample mnemonics → .env (dev helper)
    common.py             # Algod client, funding, shared helpers
    create_ticket_asa.py  # Mint ticket ASA (decimals=0)
    deploy_router.py      # Compile + deploy Router
    deploy_superfan.py    # Compile + deploy Superfan
    fund.py               # Funding utilities
    list_apps.py          # Enumerate apps; print global state
    quest_ops.py          # Superfan: opt-in, add_points, claim_tier
    resale_via_router.py  # CLI: resale group via Router
```

---

## License

Apache-2.0 © 2025 Joltkin LLC.
