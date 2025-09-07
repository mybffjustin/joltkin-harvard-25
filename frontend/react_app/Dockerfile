# frontend/react_app/Dockerfile
# -----------------------------------------------------------------------------
# React (Vite) build -> Nginx static serve
# -----------------------------------------------------------------------------

FROM node:22-alpine AS build
ARG NPM_VERSION=11.6.0
RUN npm i -g "npm@${NPM_VERSION}" --no-fund --no-audit
WORKDIR /app

# OPTIONAL: if your build script runs `algokit` (e.g. generate typed clients),
# install it safely in a venv and expose to PATH for this stage only.
RUN apk add --no-cache python3 py3-pip \
 && python3 -m venv /opt/py \
 && /opt/py/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/py/bin/pip install --no-cache-dir algokit \
 && /opt/py/bin/algokit --version
ENV PATH="/opt/py/bin:${PATH}"

COPY frontend/react_app/ ./

RUN --mount=type=cache,target=/root/.npm \
    sh -c 'if [ -f package-lock.json ]; then npm ci; else npm install; fi'

# build with your envs
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
COPY frontend/react_app/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --retries=6 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1
