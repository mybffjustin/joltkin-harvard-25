<!-- frontend/README.md -->
# Joltkin X Algorand — Demo Stack (Royalty Router, Superfan Pass, QR Ops)

Operator-friendly demos for ticketing and superfans on **Algorand TestNet**.
Includes:

* **Royalty Router** (PyTeal): primary buy with split payouts; resale with artist royalty
* **Ticket ASA** minting (whole-number tickets)
* **Superfan Pass**: points + tiers (local state)
* **React Frontend** (Vite + NGINX) for public QR flows & a staff screen
* **Streamlit Operator Console** for on-site/hackathon ops (mint, deploy, buy/resale, points, print packs)

> ⚠️ TestNet only. Mnemonics are accepted for demo convenience. **Do not** use production secrets here.

## Table of Contents

* [Architecture](#architecture)
* [Quickstart (Docker Compose)](#quickstart-docker-compose)
* [Quickstart (Local Dev)](#quickstart-local-dev)
* [Environment](#environment)
* [Directory Layout](#directory-layout)
* [Operator Workflows](#operator-workflows)
* [Printing: QR Packs](#printing-qr-packs)
* [Backend Scripts](#backend-scripts)
* [Development Tips](#development-tips)
* [Troubleshooting](#troubleshooting)
* [Security Notes](#security-notes)
* [License](#license)

## Architecture

```markdown
┌──────────────────────────────────────────────────────────────────────┐
│  React Frontend (Vite → NGINX)                                       │
│  • Public QR pages (/mint, /stamp, /staff.html)                      │
│  • Built assets served by NGINX                                      │
└───────────────▲──────────────────────────────────────────────────────┘
                │ deep links
┌───────────────┴──────────────────────────────────────────────────────┐
│  Streamlit Operator Console                                          │
│  • One-click QuickStart (Mint ASA → Deploy Router → Opt-ins)         │
│  • Buy/Resale flows (grouped tx)                                     │
│  • Superfan: deploy, add points, claim tiers, leaderboards           │
│  • QR Print Packs (PNG/PDF)                                          │
└───────────────▲──────────────────────────────────────────────────────┘
                │ Algod / Indexer (TestNet)
┌───────────────┴──────────────────────────────────────────────────────┐
│  Algorand TestNet                                                    │
│  • Apps from PyTeal: Router, Superfan                                │
│  • ASAs as tickets/badges                                            │
└──────────────────────────────────────────────────────────────────────┘
```

## Quickstart (Docker Compose)

From repo root:

```bash
cd infra_devops/docker
docker compose up --build -d
```

Services:

* **frontend** → NGINX serving built React app on `http://localhost:5173`
* **streamlit** → Operator console on `http://localhost:8501`
* **backend** (optional utility container) → runs sample script by default

The compose file already:

* Builds from the **repo root**
* Healthchecks the frontend
* Mounts `.env` **read-only** into Streamlit

Stop & clean:

```bash
docker compose down -v
```

### Get the latest Streamlit changes instantly (dev)

For tight dev loop, bind-mount the Streamlit source so edits reload without rebuilding:

```yaml
# infra_devops/docker/docker-compose.yml  (add under streamlit:)
    volumes:
      - ../../.env:/app/.env:ro
      - ../../frontend/streamlit_app/:/app/streamlit_app/:rw  # <— live code mount
```

Streamlit auto-reloads on file save. (No rebuild needed.)

## Quickstart (Local Dev)

### 1) Python (Streamlit console)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp env.example .env   # fill values as needed
streamlit run frontend/streamlit_app/app.py  # http://localhost:8501
```

To enable PDF posters/labels:

```bash
pip install qrcode[pil] reportlab pillow
```

### 2) Node (Frontend)

```bash
cd frontend/react_app
npm ci
npm run build         # outputs to frontend/react_app/dist (served by NGINX in Docker)

# or for local dev preview:
npm run dev           # http://localhost:5173
```

> The Docker image builds the React app and serves it from NGINX on port **5173** (host).

## Environment

The system uses `.env` (via `python-dotenv` in Streamlit; NGINX/React use build args). Defaults are set for Algonode TestNet.

| Variable            | Purpose                             | Default                              |
| ------------------- | ----------------------------------- | ------------------------------------ |
| `ALGOD_URL`         | Algod endpoint                      | `https://testnet-api.algonode.cloud` |
| `ALGOD_TOKEN`       | Algod API token                     | *(empty OK for Algonode)*            |
| `INDEXER_URL`       | Indexer endpoint                    | `https://testnet-idx.algonode.cloud` |
| `INDEXER_TOKEN`     | Indexer token                       | *(empty)*                            |
| `FRONTEND_BASE_URL` | Base URL for deep links (React app) | `http://localhost:5173`              |
| `CREATOR_MNEMONIC`  | TestNet mnemonic (creator)          | *(unset)*                            |
| `SELLER_MNEMONIC`   | TestNet mnemonic (seller)           | *(unset)*                            |
| `BUYER_MNEMONIC`    | TestNet mnemonic (buyer/user)       | *(unset)*                            |
| `ADMIN_MNEMONIC`    | TestNet mnemonic (superfan admin)   | *(unset)*                            |

> In Compose, `.env` is mounted into the Streamlit container **read-only**.

## Directory Layout

```markdown
.
├── backend
│   ├── contracts/               # PyTeal: router.py, superfan_pass.py
│   ├── Dockerfile               # (optional) tools image
│   └── scripts/                 # CLI helpers (deploy, buy/resale, etc.)
├── frontend
│   ├── react_app/               # React + Vite app (public QR UX)
│   │   ├── Dockerfile           # builds app → served by NGINX
│   │   └── dist/                # build output (index.html, assets, staff.html)
│   └── streamlit_app/           # Operator console
│       ├── app.py               # tabs + composition
│       ├── core/                # config, clients, constants
│       ├── pages/               # deploy_router, trade, superfan, harvard, venue, tools
│       ├── services/            # algorand SDK helpers, QR/PDF generation
│       └── ui/                  # keys, layout, sidebar, shared components
├── infra_devops
│   └── docker/docker-compose.yml
├── env.example                  # copy to .env and edit
├── requirements.txt             # Streamlit + Algorand SDK deps
├── pyproject.toml
└── README.md
```

## Operator Workflows

### One-Click QuickStart (Streamlit → **Deploy Router** tab)

* **Mint Ticket ASA** (auto-fund & retry on MBR errors)
* **Deploy Royalty Router** from PyTeal (compile on the fly)
* **Opt-in** buyer/seller (if mnemonics provided)
* **Prefund** Router app address for inner tx fees

### Buy / Resale (Streamlit → **Buy/Resale** tab)

* **Primary buy**: `[AppCall, Payment, ASA]` grouped, with split payouts
* **Resale**: buyer pays Router; holder transfers ASA; artist royalty enforced
* Guardrails: min balance checks, opt-in checks, clear error messages

### Superfan Pass (Streamlit → **Superfan** tab)

* Deploy app; admin **add points**; user **claim tier**
* simple leaderboard via Indexer (**Top wallets**)

## Printing: QR Packs

From Streamlit **HARVARD Partner / Venue Partner** tabs:

* Generate a ZIP containing:

  * `posters.pdf` (one QR per page)
  * `stickers_letter.pdf` (3X5) and `stickers_a4.pdf` (3X8)
  * `qrs/*.png`
  * `MANIFEST.csv` (filename, URL, caption, group, and `utm_*`)
* UTM parameters are appended to URLs for tracking.

> PDFs require `reportlab` + `pillow`. PNG QRs require `qrcode[pil]`.

## Backend Scripts

Inside `backend/scripts` (runnable in your host venv or a Python container):

```bash
# List created apps for an account
python backend/scripts/list_apps.py --details

# Deploy Superfan (admin must be funded)
python backend/scripts/deploy_superfan.py

# Deploy Router (after ASA minted)
python backend/scripts/deploy_router.py

# Primary buy / Resale (demo flows)
python backend/scripts/buy_ticket.py
python backend/scripts/resale_via_router.py
```

> Scripts read `.env`. Use the Streamlit console for most demo flows—scripts are helpful for CI or headless checks.

## Development Tips

* **Hot reload Streamlit**: bind-mount `frontend/streamlit_app` in Compose (see above).
* **Frontend tweaks**: `cd frontend/react_app && npm run dev` while the NGINX container serves the last build. Rebuild to publish changes to Docker.
* **Size warnings (Vite)**: consider dynamic imports / manual chunks if bundles exceed 700kb.
* **Indexing/Leaderboards**: set `INDEXER_URL` to a reachable TestNet indexer.
* **Public scans**: set `FRONTEND_BASE_URL` to a publicly reachable URL before printing posters.

## Troubleshooting

* **Duplicate widget IDs in Streamlit**
  Always provide a **unique `key=`** for `st.*_input`, especially when labels/values repeat across tabs. This repo uses `ui/keys.py` (`k(page, name)`).

* **`balance ... below min` / MBR errors**
  Use the console’s auto-fund features or top-up accounts. Router app may also need a small prefund for inner tx fees.

* **“invalid ApplicationArgs index”**
  Group order or `accounts[]` wrong. Router expects **`[AppCall, Payment, ASA]`** with the `AppCall` at index 0.

* **Leaderboards empty**
  Verify `INDEXER_URL`, correct app id, and that points exist in local state.

* **Docker cached builds**
  For frontend image: `docker compose build --no-cache frontend` (or run `docker compose watch` if you enable it and bind-mount sources for dev).

## Security Notes

* Never use real production mnemonics here; TestNet only.
* Mount `.env` **read-only** (`:ro`) in containers.
* Streamlit stores mnemonics in memory only; inputs are password fields, but this is still a **demo tool**.
* Consider rate-limiting and minimal logging if you host publicly.

## License

**Apache-2.0** © 2025 Joltkin LLC.
