import { useEffect, useState, type ReactElement } from 'react'

import { getHealth, type BackendHealth } from './api.ts'
import { Shell } from './components/Shell.tsx'
import { ApprovalPage } from './pages/ApprovalPage.tsx'
import { InboxPage } from './pages/InboxPage.tsx'
import { LoginPage } from './pages/LoginPage.tsx'
import { OrderPage } from './pages/OrderPage.tsx'
import { PermissionsPage } from './pages/PermissionsPage.tsx'
import { RecordPage } from './pages/RecordPage.tsx'

type BackendStatus = 'loading' | BackendHealth

// The approve_url in a cart is /carts/{id}. Caddy serves index.html for every path.
const CART_PATH = /^\/carts\/([^/]+)$/
const RECORD_PATH = /^\/carts\/([^/]+)\/record$/
const ORDER_PATH = /^\/orders\/([^/]+)$/
const STATIC_PAGES: Readonly<Record<string, () => ReactElement>> = {
  // The main user comes to decide on orders, so the root opens the inbox.
  '/': InboxPage,
  '/health': HealthPage,
  '/login': LoginPage,
  '/inbox': InboxPage,
  '/permissions': PermissionsPage,
}

// A bad percent escape makes decodeURIComponent throw during render. The path then opens the
// inbox instead of a blank page.
function decodeId(raw: string | undefined): string | null {
  if (raw === undefined) {
    return null
  }

  try {
    return decodeURIComponent(raw)
  } catch {
    return null
  }
}

// ponytail: plain path match, no router dependency. Add one when pages need links and history.
function pageFor(path: string): ReactElement | null {
  const recordId = decodeId(RECORD_PATH.exec(path)?.[1])
  if (recordId !== null) {
    return <RecordPage cartId={recordId} />
  }

  const cartId = decodeId(CART_PATH.exec(path)?.[1])
  if (cartId !== null) {
    return <ApprovalPage cartId={cartId} />
  }

  const orderId = decodeId(ORDER_PATH.exec(path)?.[1])
  if (orderId !== null) {
    return <OrderPage orderId={orderId} />
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

// An unknown path opens the inbox, so a mistyped link still shows the orders that wait.
export function App(): ReactElement {
  const path = window.location.pathname
  const page = pageFor(path)
  if (page === null) {
    return (
      <Shell path="/">
        <InboxPage />
      </Shell>
    )
  }

  return <Shell path={path}>{page}</Shell>
}
