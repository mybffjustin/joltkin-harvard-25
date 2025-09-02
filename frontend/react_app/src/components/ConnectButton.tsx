// frontend/react_app/src/components/ConnectButton.tsx
import { useRef, useState } from 'react'
import { startPairing } from '../wc/pairing'

export default function ConnectButton() {
  const [session, setSession] = useState<any>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const onConnect = async () => {
    if (!canvasRef.current) return
    const s = await startPairing(canvasRef.current)
    setSession(s)
  }

  return (
    <div className="p-4">
      <button onClick={onConnect}>Connect Wallet (WC v2)</button>
      <div className="mt-3">
        <canvas ref={canvasRef} />
      </div>
      {session && <pre>{JSON.stringify(session, null, 2)}</pre>}
    </div>
  )
}
