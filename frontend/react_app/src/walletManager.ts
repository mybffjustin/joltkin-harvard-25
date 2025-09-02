// frontend/react_app/src/walletManager.ts
import { WalletManager, WalletId, NetworkId } from '@txnlab/use-wallet'

// Minimal: enable a couple of wallets and start on TestNet.
// (MainNet/TestNet/BetaNet come pre-configured via Nodely defaults.)
export const manager = new WalletManager({
  wallets: [
    WalletId.PERA,
    WalletId.DEFLY,     // add/remove as you like
    // WalletId.EXODUS,
    // { id: WalletId.WALLETCONNECT, options: { projectId: import.meta.env.VITE_REOWN_PROJECT_ID! } },
  ],
  defaultNetwork: NetworkId.TESTNET
})
