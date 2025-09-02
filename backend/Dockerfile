# backend/Dockerfile
# -----------------------------------------------------------------------------
# SPDX-License-Identifier: Apache-2.0
# Hardened image for Algorand CLI tools + contracts (no root at runtime).
# Build from REPO ROOT:  docker build -f backend/Dockerfile .
# -----------------------------------------------------------------------------

FROM python:3.12-slim AS base

# --- Runtime hygiene ----------------------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Minimal OS deps (SSL, curl; add build-essential only if you compile wheels)
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*

# Non-root user
ARG APP_USER=app
ARG APP_UID=10001
RUN useradd -m -u "${APP_UID}" -s /bin/bash "${APP_USER}"

# Isolated venv (kept outside /app to avoid bind-mount shadowing)
ENV VENV_PATH=/opt/venv
RUN python -m venv "${VENV_PATH}" && \
    "${VENV_PATH}/bin/pip" install --upgrade pip wheel
ENV PATH="${VENV_PATH}/bin:${PATH}"

# --- App layout ---------------------------------------------------------------
WORKDIR /app

# Install Python deps early for better layer caching
# Uses the repo-root requirements.txt
COPY requirements.txt /app/requirements.txt
RUN pip install --disable-pip-version-check -r /app/requirements.txt

# Copy backend code only (contracts + scripts)
COPY --chown=${APP_USER}:${APP_USER} backend/contracts  /app/backend/contracts
COPY --chown=${APP_USER}:${APP_USER} backend/scripts    /app/backend/scripts

# Optional: provide a sample env inside the image; at runtime you can
# mount a real .env (recommended) via docker compose.
# COPY --chown=${APP_USER}:${APP_USER} .env.sample       /app/.env

# Make backend importable (e.g., "from backend.scripts import …")
ENV PYTHONPATH=/app

# Drop privileges
USER ${APP_USER}

# Default working directory where scripts live
WORKDIR /app/backend/scripts

# Simple healthcheck: verify Python + algosdk import
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD python -c "import algosdk; print('ok')" >/dev/null 2>&1 || exit 1

# No default long-running process; this image is for CLI tools.
# Override the command, e.g.:
#   docker run --rm -it --env-file .env backend-img \
#     python buy_ticket.py --app 123 --asa 456 --price 1000000
CMD ["python", "--version"]
