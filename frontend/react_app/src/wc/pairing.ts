// frontend/react_app/src/wc/pairing.ts
import QRCode from 'qrcode'
import { getSignClient, ALG_NS, CHAINS, REQUIRED_METHODS, REQUIRED_EVENTS } from './signClient'

export async function startPairing(canvas: HTMLCanvasElement) {
  const client = await getSignClient()

  // Create a pairing proposal and get a URI
  const { uri, approval } = await client.connect({
    requiredNamespaces: {
      [ALG_NS]: {
        chains: CHAINS,
        methods: REQUIRED_METHODS,
        events: REQUIRED_EVENTS,
      }
    }
  })

  if (uri) {
    // Render QR into a canvas (or use your own modal)
    await QRCode.toCanvas(canvas, uri)
  }

  // Wait for wallet approval (user scans QR in Pera/Defly/etc.)
  const session = await approval()
  return session
}
