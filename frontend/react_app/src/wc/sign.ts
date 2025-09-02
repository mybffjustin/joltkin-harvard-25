// frontend/react_app/src/wc/sign.ts
import { getSignClient, ALG_NS, CHAINS } from './signClient'

// txnPayload should be what your wallet expects (e.g., encoded txn(s))
// Confirm the exact RPC schema supported by your target Algorand wallets.
export async function requestSign(sessionTopic: string, txnPayload: unknown) {
  const client = await getSignClient()

  const result = await client.request({
    topic: sessionTopic,
    chainId: CHAINS[0],                 // e.g., 'algorand:mainnet'
    request: {
      method: 'algo_signTxn',          // confirm exact method your wallet supports
      params: [txnPayload],            // shape depends on wallet spec
    }
  })

  return result
}
