// frontend/react_app/src/wc/signClient.ts
import SignClient from '@walletconnect/sign-client'

let client: SignClient | null = null

export async function getSignClient() {
  if (client) return client
  client = await SignClient.init({
    // get this from your Reown/WC project dashboard
    projectId: import.meta.env.VITE_REOWN_PROJECT_ID,
    // optional but recommended
    relayUrl: 'wss://relay.walletconnect.com',
    metadata: {
      name: 'Joltkin Harvard 25',
      description: 'Algorand dApp',
      url: import.meta.env.VITE_APP_URL ?? window.location.origin,
      icons: ['https://yourcdn/icon.png']
    }
  })
  return client
}

export const ALG_NS = 'algorand'
// pick the chains you support (example names; set to your actual CAIP chain ids)
export const CHAINS = ['algorand:mainnet'] // add 'algorand:testnet' as needed

export const REQUIRED_METHODS = [
  // Use the exact method names your target wallets support.
  // Commonly: 'algo_signTxn' (and optionally group/sign logic).
  'algo_signTxn'
]

export const REQUIRED_EVENTS: string[] = []
