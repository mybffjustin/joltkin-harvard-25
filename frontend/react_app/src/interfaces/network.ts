// frontend/react_app/src/interfaces/network.ts
export type AlgodConfig = {
  baseServer: string
  port?: string | number
  token?: string
  headers?: Record<string, string>
  /** Optional display name; used by Account.ts etc. */
  network?: 'LocalNet' | 'TestNet' | 'MainNet' | string
}
