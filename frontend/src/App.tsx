import { useEffect, useState, type ReactElement } from 'react'

import { getHealth, type BackendHealth } from './api.ts'

type BackendStatus = 'loading' | BackendHealth

export function App(): ReactElement {
  const [status, setStatus] = useState<BackendStatus>('loading')

  useEffect(() => {
    getHealth()
      .then((health) => {
        setStatus(health)
      })
      .catch(() => {
        setStatus('down')
      })
  }, [])

  return (
    <main>
      <h1>Junction 2026</h1>
      <p>Backend: {status}</p>
    </main>
  )
}
