# frontend/streamlit_app/core/config.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Centralized, immutable application configuration for the Streamlit operator UI.

This module defines a frozen `Settings` dataclass whose fields are populated
from environment variables (loaded via python-dotenv if a `.env` file is
present). The resulting singleton `settings` is imported by other modules to
avoid scattering `os.getenv` calls throughout the codebase.

Design goals
------------
- **Single source of truth**: All tunables live here; other modules consume
  `settings` rather than reading environment variables directly.
- **Immutability**: `@dataclass(frozen=True)` prevents accidental mutation at
  runtime. Changes require process restart (or re-instantiation in tests).
- **Fast import**: Only minimal work at import time (dotenv load + dataclass
  construction). No network calls or validation here.
- **Safe defaults**: Reasonable defaults target Algonode TestNet endpoints.
  Secrets default to empty strings (or benign placeholders) to prevent
  accidental leakage or unexpected behavior.

Security notes
--------------
- Do not commit real mnemonics or sensitive tokens into `.env`. Treat this file
  as development convenience only; prefer read-only mounts in containerized
  deployments.
- The `ALGOD_TOKEN` default here is a 64-character "a" string to satisfy client
  constructors that expect a token-like value; most public providers (e.g.,
  Algonode) accept an empty token. Override in `.env` as needed.

Testing
-------
- In unit/integration tests, set environment variables **before** importing this
  module, or monkeypatch module attributes after import:
      >>> import importlib, os
      >>> os.environ["ALGOD_URL"] = "http://localhost:4001"
      >>> import frontend.streamlit_app.core.config as cfg
      >>> importlib.reload(cfg)
      >>> assert cfg.settings.ALGOD_URL == "http://localhost:4001"
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load key-value pairs from a local `.env` file into process environment, if
# present. `override=False` by default, so pre-set env vars take precedence.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    """
    Immutable application settings.

    Each attribute is populated from the corresponding environment variable;
    when unset, a documented default is used. See repository `.env.example`
    for a template of common values.
    """

    # --- Algod (consensus node) endpoint configuration -----------------------
    # Base URL for the Algorand node RPC endpoint (TestNet by default).
    ALGOD_URL: str = os.getenv("ALGOD_URL", "https://testnet-api.algonode.cloud")
    # API token for the Algod endpoint. For some public providers, this can be
    # blank. We default to a 64-char placeholder to satisfy strict validators.
    ALGOD_TOKEN: str = os.getenv("ALGOD_TOKEN", "a" * 64)

    # --- Indexer (optional) endpoint configuration ---------------------------
    # Base URL for Indexer queries (leaderboards, history). Optional.
    INDEXER_URL: str = os.getenv("INDEXER_URL", "https://testnet-idx.algonode.cloud")
    # API token for Indexer; often blank for public providers.
    INDEXER_TOKEN: str = os.getenv("INDEXER_TOKEN", "")

    # --- Frontend deep-link base ---------------------------------------------
    # Public base URL for the React app; used to compose QR deep links.
    FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")

    # --- Prefilled payout/admin defaults (non-sensitive placeholders) --------
    # Default artist payout address (for quick demos). Override in `.env`.
    ARTIST_ADDR: str = os.getenv(
        "ARTIST_ADDR",
        "",
    )
    # Default seller address used in Router demos. Override in `.env`.
    SELLER_ADDR_PREF: str = os.getenv(
        "SELLER_ADDR_PREF",
        "",
    )
    # Default Superfan admin address for points/tier admin flows. Override.
    ADMIN_ADDR_PREF: str = os.getenv(
        "ADMIN_ADDR_PREF",
        "",
    )


# Singleton settings object imported by consumers.
settings = Settings()
