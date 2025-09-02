# frontend/react_app/Dockerfile
# -----------------------------------------------------------------------------
# React (Vite) build -> Nginx static serve
# Build context MUST be the repo root: ../../ (from infra_devops/docker)
# -----------------------------------------------------------------------------

FROM node:22-alpine AS build
ARG NPM_VERSION=11.5.2
RUN npm i -g "npm@${NPM_VERSION}" --no-fund --no-audit
WORKDIR /app

# Copy the entire app (incl. lockfile if present)
COPY frontend/react_app/ ./

# Install deps (prefer lockfile if available)
# Uses BuildKit cache for faster npm installs if enabled
RUN --mount=type=cache,target=/root/.npm \
    sh -c 'if [ -f package-lock.json ]; then npm ci; else npm install; fi'

# Build with Vite; inject envs at build time
ARG VITE_ALGOD_URL
ARG VITE_ALGOD_TOKEN
ARG VITE_NETWORK=TestNet
ARG VITE_ROUTER_APP_ID
ARG VITE_TICKET_ASA_ID
ARG VITE_SUPERFAN_APP_ID
ARG VITE_SUPERFAN_ADMIN_ADDR
ENV VITE_ALGOD_URL=${VITE_ALGOD_URL} \
    VITE_ALGOD_TOKEN=${VITE_ALGOD_TOKEN} \
    VITE_NETWORK=${VITE_NETWORK} \
    VITE_ROUTER_APP_ID=${VITE_ROUTER_APP_ID} \
    VITE_TICKET_ASA_ID=${VITE_TICKET_ASA_ID} \
    VITE_SUPERFAN_APP_ID=${VITE_SUPERFAN_APP_ID} \
    VITE_SUPERFAN_ADMIN_ADDR=${VITE_SUPERFAN_ADMIN_ADDR}

RUN npm run build

# -----------------------------------------------------------------------------

FROM nginx:1.29-alpine AS runtime

# SPA-friendly nginx config
COPY frontend/react_app/nginx.conf /etc/nginx/conf.d/default.conf

# Built static assets
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --retries=6 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
