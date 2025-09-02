# frontend/streamlit_app/core/clients.py
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

"""
Client factories for Algorand services used by the Streamlit operator console.

This module exposes two cached constructors:

- `get_algod()`   → `algosdk.v2client.algod.AlgodClient`
- `get_indexer()` → `Optional[algosdk.v2client.indexer.IndexerClient]`

Both are wrapped with `@st.cache_resource` so that:
  * A single client instance is created per Streamlit process/session,
    avoiding unnecessary socket creation and TLS handshakes.
  * The cached instance persists across reruns triggered by UI interaction.
  * Objects are stored as resources (not pickled), which is appropriate for
    network clients.

Environment configuration is sourced from `core.config.settings`, which loads
`.env` via python-dotenv. For Algonode endpoints, the token may be blank.

Security notes:
  * These factories read tokens from environment settings and never log them.
  * Streamlit resource cache retains in-memory references only; it does not
    serialize secrets to disk.
  * If credentials or endpoints change at runtime, you must clear the cache
    (e.g., "Rerun" with cache clear, or programmatically) to force re-creation.

Failure behavior:
  * `get_algod()` will raise immediately if inputs are invalid (constructor does
    minimal validation); callers should handle request-time errors.
  * `get_indexer()` returns `None` if the Indexer client cannot be constructed
    (e.g., missing/invalid URL or token). Callers should branch accordingly.

Testing:
  * In unit tests, monkeypatch `settings.ALGOD_URL`, `settings.ALGOD_TOKEN`,
    `settings.INDEXER_URL`, and `settings.INDEXER_TOKEN` before the first call,
    or clear Streamlit's resource cache between tests to ensure isolation.
"""


import streamlit as st
from algosdk.v2client import algod, indexer

from .config import settings


@st.cache_resource(show_spinner=False)
def get_algod() -> algod.AlgodClient:
    """
    Construct (once) and return a cached Algod (consensus node) client.

    Returns:
        AlgodClient: A configured client ready to make RPC calls.

    Notes:
        * Uses `settings.ALGOD_URL` and `settings.ALGOD_TOKEN`.
        * Many public providers (e.g., Algonode) accept an empty token.
        * This function does not perform a health check; network/auth errors
          surface when the first request is executed.

    Streamlit:
        `cache_resource` ensures a single instance is reused across reruns.
        Spinner is disabled because construction is fast and synchronous.
    """
    # No eager validation here: construction is cheap; defer errors to call time.
    return algod.AlgodClient(settings.ALGOD_TOKEN, settings.ALGOD_URL)


@st.cache_resource(show_spinner=False)
def get_indexer() -> indexer.IndexerClient | None:
    """
    Construct (once) and return a cached Indexer client, or None if unavailable.

    Returns:
        Optional[IndexerClient]: A configured Indexer client, or `None` when
        construction fails (e.g., unset/invalid URL or token).

    Rationale:
        Indexer is optional for this app (used for leaderboards/queries). Rather
        than crash the UI when misconfigured, we return `None` and let callers
        degrade gracefully (e.g., hide leaderboards).

    Caveat:
        Fail-fast at call time is still possible if the endpoint is reachable
        but unhealthy; callers should handle request exceptions.

    Streamlit:
        If construction fails, `None` is cached. Clear the resource cache if you
        later fix environment variables and want to retry within the same
        process.
    """
    try:
        return indexer.IndexerClient(settings.INDEXER_TOKEN, settings.INDEXER_URL)
    except Exception:
        # Intentionally broad: misconfigurations (bad URL, missing deps) or
        # environment constraints should not bring down the app. Callers must
        # handle the `None` case.
        return None
