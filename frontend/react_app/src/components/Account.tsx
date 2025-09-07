// frontend/react_app/src/components/Account.tsx
import { useWallet } from '@txnlab/use-wallet-react'
import { useMemo } from 'react'
import { ellipseAddress } from '../utils/ellipseAddress'
import { getAlgodConfigFromViteEnvironment } from '../utils/network/getAlgoClientConfigs'

const Account = () => {
  const { activeAddress } = useWallet()
  const algoConfig = getAlgodConfigFromViteEnvironment()

  const networkName = useMemo(() => {
    const network = algoConfig.network ?? ''
    return network === '' ? 'localnet' : network.toLocaleLowerCase()
  }, [algoConfig.network])

  return (
    <div>
      <a className="text-xl" target="_blank" href={`https://lora.algokit.io/${networkName}/account/${activeAddress}/`}>
        Address: {ellipseAddress(activeAddress)}
      </a>
      <div className="text-xl">Network: {networkName}</div>
    </div>
  )
}

export default Account
