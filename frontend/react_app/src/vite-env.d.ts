/// <reference types="vite/client" />
/* src/vite-env.d.ts */

interface ImportMetaEnv {
  readonly VITE_ALGOD_URL: string
  readonly VITE_ALGOD_TOKEN: string
  readonly VITE_NETWORK: string
  readonly VITE_ROUTER_APP_ID: string
  readonly VITE_TICKET_ASA_ID: string
  readonly VITE_SUPERFAN_APP_ID: string
  readonly VITE_SUPERFAN_ADMIN_ADDR: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
