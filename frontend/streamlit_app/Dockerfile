# frontend/streamlit_app/Dockerfile
# -----------------------------------------------------------------------------
# SPDX-License-Identifier: Apache-2.0
# Streamlit operator console + Algorand SDK tools (new repo layout)
# Build context should be the REPO ROOT. In compose:
#   build:
#     context: ../..
#     dockerfile: frontend/streamlit_app/Dockerfile
# -----------------------------------------------------------------------------

FROM python:3.12-slim AS base

# --- System setup -------------------------------------------------------------
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Minimal runtime libs for Pillow/ReportLab QR/PDF generation
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      build-essential \
      libjpeg62-turbo \
      zlib1g \
      libfreetype6 \
      liblcms2-2 \
      libtiff6 \
      libwebp7 \
      libpng16-16 \
      ca-certificates \
      curl; \
    rm -rf /var/lib/apt/lists/*

# Non-root user
ARG APP_USER=app
ARG APP_UID=10001
RUN useradd -m -u "${APP_UID}" -s /bin/bash "${APP_USER}"

# venv for clarity
ENV VENV_PATH=/opt/venv
RUN python -m venv "${VENV_PATH}" && \
    "${VENV_PATH}/bin/pip" install --upgrade pip wheel
ENV PATH="${VENV_PATH}/bin:${PATH}"

WORKDIR /app

# --- Dependencies (leverage cache) -------------------------------------------
# requirements.txt is at repo root
COPY requirements.txt /app/requirements.txt
RUN pip install --disable-pip-version-check -r /app/requirements.txt

# --- App code (new paths) -----------------------------------------------------
# NOTE: Build context must be the repo root so these paths resolve.
# Copy the Streamlit app
COPY --chown=${APP_USER}:${APP_USER} frontend/streamlit_app/ /app/streamlit_app/
# Copy contracts so Streamlit can compile PyTeal (app expects /app/contracts)
COPY --chown=${APP_USER}:${APP_USER} backend/contracts/       /app/contracts/
# Provide a sample env inside the image (actual runtime env is bind-mounted)
COPY --chown=${APP_USER}:${APP_USER} .env.example              /app/.env

# Drop privileges
USER ${APP_USER}

EXPOSE 8501

# Healthcheck
HEALTHCHECK --interval=15s --timeout=5s --retries=6 \
  CMD curl -fsS http://127.0.0.1:8501/_stcore/health | grep -q "ok" || exit 1

# Run Streamlit
CMD ["streamlit", "run", "streamlit_app/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
