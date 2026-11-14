import { useCallback, useEffect, useState, type ReactElement } from 'react'

import { getAudit, getCart, getSession, type AuditTrail, type Cart, type Session } from '../api.ts'
import { CartReview } from '../components/CartReview.tsx'
import { isSignedOut, redirectToLogin } from '../session.ts'

interface ApprovalPageProps {
  readonly cartId: string
}

interface PageData {
  readonly session: Session
  readonly cart: Cart
  readonly audit: AuditTrail | null
}

type LoadState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed' }
  | { readonly kind: 'ready'; readonly data: PageData }

// The session comes first, so a signed out user never gets a cart request. The audit only
// adds the agent name and the timeline: the page still works without it (open question 3).
async function loadPage(cartId: string): Promise<PageData> {
  const session = await getSession()
  const [cart, audit] = await Promise.all([getCart(cartId), getAudit(cartId).catch(() => null)])

  return {
    session,
    cart,
    audit,
  }
}

// The approve_url in a cart opens this page.
export function ApprovalPage({ cartId }: ApprovalPageProps): ReactElement {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(() => {
    loadPage(cartId)
      .then((data) => {
        setState({ kind: 'ready', data })
      })
      .catch((error: unknown) => {
        if (isSignedOut(error)) {
          redirectToLogin()
          return
        }

        setState({ kind: 'failed' })
      })
  }, [cartId])

  useEffect(load, [load])

  if (state.kind === 'loading') {
    return (
      <main>
        <p className="muted" role="status">
          Loading the order.
        </p>
      </main>
    )
  }

  if (state.kind === 'failed') {
    return (
      <main className="stack">
        <p className="alert" role="alert">
          The order could not be loaded.
        </p>
        <button
          className="button button-primary"
          type="button"
          onClick={() => {
            setState({ kind: 'loading' })
            load()
          }}
        >
          Retry
        </button>
      </main>
    )
  }

  const { session, cart, audit } = state.data
  if (cart.status !== 'waiting') {
    return (
      <main>
        <p>This order is no longer waiting for approval.</p>
      </main>
    )
  }

  return (
    <main className="stack">
      <CartReview cart={cart} buyerId={session.buyerId} agentName={audit?.agentName ?? null} />
      <div className="actions">
        <button className="button button-primary" type="button">
          Approve order
        </button>
        <button className="button button-text" type="button">
          Reject
        </button>
      </div>
    </main>
  )
}
