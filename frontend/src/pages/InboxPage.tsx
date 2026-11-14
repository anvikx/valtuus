import { useCallback, useEffect, useState, type ReactElement } from 'react'

import { getSession, listCarts, type Cart, type CartStatus } from '../api.ts'
import { formatDateTime } from '../format.ts'
import { isSignedOut, redirectToLogin } from '../session.ts'

type ClosedStatus = Exclude<CartStatus, 'waiting'>

interface InboxData {
  readonly buyerId: string
  readonly waiting: readonly Cart[]
  readonly decided: readonly Cart[]
}

type LoadState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed' }
  | { readonly kind: 'ready'; readonly data: InboxData }

const STATUS_LABEL: Readonly<Record<ClosedStatus, string>> = {
  ordered: 'Ordered',
  rejected: 'Rejected',
  expired: 'Expired',
  denied: 'Not allowed',
  withdrawn: 'Cancelled',
  closed: 'No approval needed',
}

// The session comes first, so a signed out user never gets a cart request.
async function loadInbox(): Promise<InboxData> {
  const session = await getSession()
  const carts = await listCarts()

  return {
    buyerId: session.buyerId,
    waiting: carts.filter((cart) => cart.status === 'waiting'),
    decided: carts.filter((cart) => cart.status !== 'waiting'),
  }
}

// The same path as the approve_url, so a cart opens on its approval page.
function cartHref(cartId: string): string {
  return `/carts/${encodeURIComponent(cartId)}`
}

// "Approve before Sun 15 Nov 17:00" for a waiting cart, "Ordered, Sat 14 Nov 10:04" for the rest.
function statusText(cart: Cart): string {
  if (cart.status === 'waiting') {
    return `Approve before ${formatDateTime(cart.approveBefore)}`
  }

  const label = STATUS_LABEL[cart.status]
  return cart.decidedAt === null ? label : `${label}, ${formatDateTime(cart.decidedAt)}`
}

function CartItem({ cart }: { readonly cart: Cart }): ReactElement {
  return (
    <li>
      <a className={`card inbox-item inbox-${cart.status}`} href={cartHref(cart.id)}>
        <span className="heading">{cart.requestText}</span>
        <span>
          {cart.total} {cart.currency} ex VAT
        </span>
        <span className="muted">{statusText(cart)}</span>
      </a>
    </li>
  )
}

interface CartSectionProps {
  readonly id: string
  readonly title: string
  readonly carts: readonly Cart[]
  readonly emptyText: string
}

function CartSection({ id, title, carts, emptyText }: CartSectionProps): ReactElement {
  return (
    <section className="stack-tight" aria-labelledby={id}>
      <h2 className="label" id={id}>
        {title} ({carts.length})
      </h2>
      {carts.length === 0 ? (
        <p className="muted">{emptyText}</p>
      ) : (
        <ul className="stack-tight" role="list">
          {carts.map((cart) => (
            <CartItem key={cart.id} cart={cart} />
          ))}
        </ul>
      )}
    </section>
  )
}

// The main user's list of carts: the ones that wait for a decision, then the decided ones.
export function InboxPage(): ReactElement {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(
    () =>
      loadInbox().then(
        (data) => {
          setState({ kind: 'ready', data })
        },
        (error: unknown) => {
          if (isSignedOut(error)) {
            redirectToLogin()
            return
          }

          setState({ kind: 'failed' })
        },
      ),
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  if (state.kind === 'loading') {
    return (
      <main>
        <p className="muted" role="status">
          Loading the inbox.
        </p>
      </main>
    )
  }

  if (state.kind === 'failed') {
    return (
      <main className="stack">
        <p className="alert" role="alert">
          The inbox could not be loaded.
        </p>
        <button
          className="button button-primary"
          type="button"
          onClick={() => {
            setState({ kind: 'loading' })
            void load()
          }}
        >
          Retry
        </button>
      </main>
    )
  }

  const { buyerId, waiting, decided } = state.data
  return (
    <main className="stack">
      <header className="stack-tight">
        <h1 className="page-title">Inbox</h1>
        <p className="muted">Buyer {buyerId}</p>
      </header>
      <CartSection
        id="waiting-title"
        title="Waiting for you"
        carts={waiting}
        emptyText="No order waits for your approval."
      />
      <CartSection
        id="decided-title"
        title="Decided"
        carts={decided}
        emptyText="No decided orders yet."
      />
    </main>
  )
}
