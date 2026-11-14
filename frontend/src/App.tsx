import { useEffect, useState, type ReactElement } from 'react'

import { getHealth, type BackendHealth } from './api.ts'
import { Shell } from './components/Shell.tsx'
import { ApprovalPage } from './pages/ApprovalPage.tsx'
import { InboxPage } from './pages/InboxPage.tsx'
import { LoginPage } from './pages/LoginPage.tsx'
import { OrderPage } from './pages/OrderPage.tsx'
import { PermissionsPage } from './pages/PermissionsPage.tsx'

type BackendStatus = 'loading' | BackendHealth

// The approve_url in a cart is /carts/{id}. Caddy serves index.html for every path.
const CART_PATH = /^\/carts\/([^/]+)$/
const ORDER_PATH = /^\/orders\/([^/]+)$/
const STATIC_PAGES: Readonly<Record<string, () => ReactElement>> = {
  '/login': LoginPage,
  '/inbox': InboxPage,
  '/permissions': PermissionsPage,
}

// ponytail: plain path match, no router dependency. Add one when pages need links and history.
function pageFor(path: string): ReactElement | null {
  const cartId = CART_PATH.exec(path)?.[1]
  if (cartId !== undefined) {
    return <ApprovalPage cartId={decodeURIComponent(cartId)} />
  }

  const orderId = ORDER_PATH.exec(path)?.[1]
  if (orderId !== undefined) {
    return <OrderPage orderId={decodeURIComponent(orderId)} />
  }

  const Page = STATIC_PAGES[path]
  return Page ? <Page /> : null
}

function HealthPage(): ReactElement {
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

export function App(): ReactElement {
  return <Shell>{pageFor(window.location.pathname) ?? <HealthPage />}</Shell>
}
