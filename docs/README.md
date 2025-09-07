<!-- docs/README.md -->
# 🎭🎶 Joltkin × Algorand — Trustless Ticketing, Resale Royalty, Superfan Pass (+ AI Discovery)

![Network: TestNet](https://img.shields.io/badge/network-TestNet-blue)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-informational)
![Algorand SDK](https://img.shields.io/badge/algosdk-v2%2Fv3-success)
![Streamlit](https://img.shields.io/badge/Streamlit-ready-brightgreen)
![React](https://img.shields.io/badge/React-Vite-blue)
![Docker Compose](https://img.shields.io/badge/docker-compose-blue)

## What it is

- **Programmable tickets (ASA)** — `decimals=0`, 1 token = 1 ticket
- **Royalty Router (PyTeal)** — `buy()` splits primary revenue; `resale()` enforces a resale royalty
- **Superfan Pass (PyTeal)** — on-chain points → tiers for loyalty/quests
- **Operator console (Streamlit)** — push-button deploy & demo; **print-ready QR packs**
- **Buyer UX (React + Pera)** — wallet-based purchase & resale
- **AI recommender (Ollama)** — “find my concert” matching with graceful local fallback
- **CLI tools & Docker** — reproducible scripts and one-command stack

> ⚠️ TestNet only. Audit, threat model, and harden before any production use.

---

## Table of Contents

- [Overview](#overview)
- [How We Meet the Hackathon Brief](#how-we-meet-the-hackathon-brief)
- [Quickstart (Local)](#quickstart-local)
- [Quickstart (Docker)](#quickstart-docker)
- [AI Recommender (Ollama)](#ai-recommender-ollama)
- [Streamlit: What to Click](#streamlit-what-to-click)
- [QR Print Packs](#qr-print-packs)
- [Smart Contracts](#smart-contracts)
- [Submission Checklist](#submission-checklist)
- [3-Minute Demo Script](#3-minute-demo-script)
- [Troubleshooting](#troubleshooting)
- [Repo Map](#repo-map)
- [License](#license)

---

## Overview

Think of Joltkin as a **digital box office + accountant + fan club**:

- **Ticket ASA** — the inventory
- **Royalty Router** — enforces primary splits & resale royalty via **atomic groups** and **inner txns**
- **Superfan Pass** — **user-owned** on-chain points and tiers
- **AI** — optional event discovery for fans (“recommend me something in Boston under $100”)

Artifacts for judging:

- 📄 Deck (Darika): `docs/joltkin-canva-darika-u-compressed.pdf`
- 🎥 Demo video & repo walkthrough: _add Loom link in this section before submission_
- 🖼️ Screens: add screenshots from Streamlit/React after your run-through

---

## How We Meet the Hackathon Brief

### Trustless payments, verifiable data, user-owned identity, programmable assets

- **Programmable asset:** `backend/scripts/create_ticket_asa.py`
- **Trustless primary/resale:** `backend/contracts/router.py` + `buy_ticket.py` + `resale_via_router.py`
- **Verifiable state:** inspect app/global/local with `list_apps.py` and `check_state.py`
- **User-owned identity:** wallets sign; no custody (React Pera integration)

### AI × blockchain (optional track)

- **Event recommender:** `frontend/streamlit_app/pages/ai_rec.py` (Ollama), with **heuristic fallback** if LLM offline

### Open marketplace (optional)

- **Peer-to-peer resale with enforced royalty** via Router `resale()` flow

---

## Quickstart (Local)

```bash
# 0) Python
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) .env (repo root)
cp env.example .env
# Fill CREATOR_/SELLER_/BUYER_/ADMIN_MNEMONIC (TestNet), ALGOD_URL/INDEXER_URL (Algonode defaults OK)

# 2) Create a ticket ASA (1 unit = 1 ticket)
python backend/scripts/create_ticket_asa.py --unit TIX --name "Joltkin Ticket" --total 1000 --decimals 0

# 3) Deploy Router (primary splits + resale royalty)
python backend/scripts/deploy_router.py \
  --artist <P1_ADDR> --p2 <P2_ADDR> --p3 <P3_ADDR> \
  --bps1 7000 --bps2 2500 --bps3 500 \
  --roy_bps 500 \
  --asa <ASA_ID> \
  --seller <PRIMARY_SELLER_ADDR>

# 4) Streamlit operator console
streamlit run frontend/streamlit_app/app.py
# http://localhost:8501
````

**Optional React (buyer UI):**

```bash
cd frontend/react_app
cp .env.example .env  # set VITE_* values
npm i
npm run dev           # http://localhost:5173
```

---

## Quickstart (Docker)

```bash
# 1) Prepare env
cp env.example .env   # fill mnemonics/endpoints

# 2) Bring up the stack
cd infra_devops/docker
docker compose up -d --build

# 3) Open
# React (nginx):       http://localhost:5173
# Streamlit console:   http://localhost:8501

# 4) One-off script inside the backend container
docker compose run --rm backend python list_apps.py --details
```

Compose file: `infra_devops/docker/docker-compose.yml` (frontend, streamlit, backend).
_Add an `ollama` service if you want LLMs inside Compose — see [AI section](#ai-recommender-ollama)._

---

## AI Recommender (Ollama)

**File:** `frontend/streamlit_app/pages/ai_rec.py` (by Mirada)

- Reads `OLLAMA_BASE_URL` and `OLLAMA_MODEL` (defaults: `http://localhost:11434`, `llama3.1:8b`)
- If Ollama is unreachable, falls back to a **simple keyword+budget matcher**
- Hardcoded events for the demo; swap in an API later

**Run locally** (outside Docker):

```bash
# Start Ollama daemon (host)
ollama serve &
# Pull a model
ollama pull llama3.1:8b

# Streamlit
streamlit run frontend/streamlit_app/app.py
# → open the AI tab: 🎵 AI Event Recommender
```

### Optional: add Ollama to Compose

```yaml
# infra_devops/docker/docker-compose.yml (example service)
  ollama:
    image: ollama/ollama:latest
    ports: ["11434:11434"]
    volumes:
      - ollama:/root/.ollama
    networks: [appnet]
# and set OLLAMA_BASE_URL=http://ollama:11434 in .env for Streamlit
```

---

## Streamlit: What to Click

1. **Deploy Router**

   - Create Demo Ticket ASA → copy ASA id
   - Deploy Router → pass p1/p2/p3, bps, royalty, ASA
   - (Optional) Opt-ins & Prefund helpers
2. **Trade**

   - Buyer opt-in → **Buy** (3-txn atomic group)
   - Holder → **Resale** to new buyer (router enforces royalty)
3. **Superfan Pass**

   - Deploy → Admin **Add Points** → User **Claim Tier**
4. **AI Recommender**

   - Preferences text → “Find my concert” (Ollama or fallback)
5. **Harvard / Venue Partner**

   - Build **print-ready QR packs** (posters + sticker sheets + manifest)

---

## QR Print Packs

**File:** `frontend/streamlit_app/services/qrprint.py`
Generates a ZIP:

- `posters.pdf`, `stickers_letter.pdf`, `stickers_a4.pdf`
- `qrs/*.png` (individual codes)
- `MANIFEST.csv` (UTM fields for tracking)

> PDFs require `reportlab` + `pillow`; PNGs use `qrcode[pil]`.

---

## Smart Contracts

### Royalty Router — `backend/contracts/router.py`

- **Globals:** `p1,p2,p3` (bytes), `bps1,bps2,bps3` (uint), `roy_bps` (uint), `asa` (uint), `seller` (bytes)
- **`buy()` group:** `[AppCall("buy"), Payment(price), AssetTransfer(1 unit)]` → inner tx splits p1/p2/p3
- **`resale()` group:** `[AppCall("resale"), Payment(price), AssetTransfer(1 unit)]` → inner tx royalty to `p1`, remainder to holder
- AppCall fee should be flat and cover inner transactions

### Superfan Pass — `backend/contracts/superfan_pass.py`

- **Global:** `admin` (bytes)
- **Local:** `points` (uint), `tier` (uint)
- **Ops:** `optin`, `add_points(amount, account)` (admin-only), `claim_tier(threshold)` (user-initiated)

---

## Submission Checklist

Use this as your final pass before submitting:

- ✅ **Built on Algorand smart contracts** (Router + Superfan Pass in PyTeal)
- ✅ **Open source** (Apache-2.0)
- ✅ **Short summary (<150 chars)**

  - _Example_: “Trustless ticketing on Algorand with primary splits, resale royalty, and a Superfan Pass — plus an AI event recommender.”
- ✅ **Full description** (problem, solution, why Algorand) — in this README + deck
- ✅ **Technical description** (SDKs, AVM features used) — contracts & scripts documented above
- ✅ **Canva slides link** — add link next to the deck file in this README
- ✅ **Custom contracts** — `router.py`, `superfan_pass.py`
- ✅ **Demo video** — add Loom link (code tour + run-through)
- ✅ **Screenshots** — Streamlit, React, AI tab
- ✅ **Attributions** — credit any templates/snippets you reuse

---

## 3-Minute Demo Script

1. **Problem → Solution (0:30)**
   “Fees & scalpers are brutal. Joltkin issues tickets as ASAs; a Router splits primary revenue and enforces resale royalty; Superfan Pass rewards loyal fans.”
2. **Architecture (0:30)**
   “Two PyTeal apps + ASA. Atomic groups guarantee fair flows. Wallets = identity; no custody.”
3. **Live Demo (1:30)**

   - Streamlit: create ASA → deploy Router → **Buy** (show split txns)
   - **Resale** (royalty enforced)
   - Superfan: add points → **Claim Tier**
   - AI tab: “Boston under \$100” → recommendation
4. **Why Algorand (0:15)**
   “Finality, low fees, AVM inner txns for precise payouts & atomicity.”
5. **Roadmap + Ask (0:15)**
   “Seat maps, issuer tools, campus pilots. Looking for partner venues & mentors.”

---

## Troubleshooting

- **“invalid group / inner txn”** → Ensure group order is `[AppCall, Payment, ASA]` and AppCall at index 0
- **Fee/MBR issues** → Prefund the app; see `backend/scripts/common.py` helpers
- **Streamlit duplicate widget keys** → use `ui/keys.py` helpers
- **Ollama 404/connection refused** → set `OLLAMA_BASE_URL`; falls back to heuristic if offline

---

## Repo Map

```bash
backend/
  contracts/
    router.py                 # Royalty router (buy/resale; splits + resale royalty)
    superfan_pass.py          # Superfan app (points & tier)
  scripts/
    buy_ticket.py             # Primary buy atomic group [AppCall, Pay, ASA]
    resale_via_router.py      # Resale atomic group via Router
    create_ticket_asa.py      # Mint ticket ASA (decimals=0)
    deploy_router.py          # Compile & deploy Router
    deploy_superfan.py        # Compile & deploy Superfan
    check_state.py            # Preflight: MBR/balances/opt-ins/prefund
    list_apps.py              # List apps; print global state
    fund.py                   # Funding helpers (µAlgos)
    codegen.py                # Generate TestNet mnemonics → .env
    common.py                 # Shared algod/client utilities

docs/
  joltkin-canva-darika-u-compressed.pdf   # Deck (Darika)

frontend/
  react_app/                  # Buyer UX (wallet flows)
    Dockerfile, nginx.conf, index.html, vite.config.ts, tsconfig*.json
    public/staff.html, manifest.webmanifest
    src/App.tsx, main.tsx, polyfills.ts
    src/components/*.tsx, wallet.tsx, walletManager.ts, wc/*, shims/*
  streamlit_app/              # Operator console
    app.py
    pages/
      deploy_router.py
      trade.py
      superfan.py
      harvard_partner.py
      venue_partner.py
      tools.py
      ai_rec.py               # 🎵 AI recommender (Mirada) (Ollama or heuristic)
    services/
      algorand.py
      qrprint.py
    core/
      clients.py, config.py, constants.py, state.py
    ui/
      components.py, keys.py, layout.py, sidebar.py

infra_devops/
  docker/docker-compose.yml   # Frontend (nginx), Streamlit, Backend (CLI). Add Ollama if desired.

env.example                    # Copy → .env (TestNet endpoints + mnemonics)
requirements.txt               # Python deps (algosdk, streamlit, qrcode, reportlab*)
pyproject.toml                 # Tooling: black, ruff, etc.
LICENSE                        # Apache-2.0
README.md                      # You are here
```

---

## License

**Apache-2.0** © 2025 Joltkin LLC
