import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'

import {
  ApiError,
  approveCart,
  getAudit,
  getCart,
  getSession,
  rejectCart,
  type AuditTrail,
  type Cart,
  type Session,
} from '../api.ts'
import { AuditTimeline } from '../components/AuditTimeline.tsx'
import { CartReview } from '../components/CartReview.tsx'
import { DecisionPanel } from '../components/DecisionPanel.tsx'
import { ResultCard } from '../components/ResultCard.tsx'
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
type DecisionCall = () => Promise<unknown>

function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.kind === 'conflict'
}

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
  const [isBusy, setIsBusy] = useState(false)
  // The call that failed, so Retry can send the same decision again.
  const [failedCall, setFailedCall] = useState<DecisionCall | null>(null)
  // A ref, not state: a second tap before React renders still reads the old isBusy.
  const isBusyRef = useRef(false)

  const load = useCallback(
    () =>
      loadPage(cartId).then(
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
    [cartId],
  )

  useEffect(() => {
    void load()
  }, [load])

  // The buttons stay disabled until the reload shows the new cart state, so the user cannot
  // send a second decision on a cart that is already decided.
  // A 409 means the cart changed first (an expiry, or a decision in another tab). The reload
  // shows that new state instead of an error.
  async function onDecideError(error: unknown, call: DecisionCall): Promise<void> {
    if (isSignedOut(error)) {
      redirectToLogin()
      return
    }

    if (isConflict(error)) {
      await load()
      return
    }

    setFailedCall(() => call)
  }

  async function decide(call: DecisionCall): Promise<void> {
    if (isBusyRef.current) {
      return
    }

    isBusyRef.current = true
    setIsBusy(true)
    setFailedCall(null)
    try {
      await call()
      await load()
    } catch (error: unknown) {
      await onDecideError(error, call)
    } finally {
      isBusyRef.current = false
      setIsBusy(false)
    }
  }

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
            void load()
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
      <main className="stack">
        <ResultCard cart={cart} status={cart.status} />
        <AuditTimeline audit={audit} requestText={cart.requestText} />
      </main>
    )
  }

  return (
    <main className="stack">
      <CartReview cart={cart} buyerId={session.buyerId} agentName={audit?.agentName ?? null} />
      {failedCall === null ? null : (
        <div className="stack-tight">
          <p className="alert" role="alert">
            Your decision was not saved.
          </p>
          <button
            className="button button-primary"
            type="button"
            disabled={isBusy}
            onClick={() => void decide(failedCall)}
          >
            Retry
          </button>
        </div>
      )}
      <DecisionPanel
        isBusy={isBusy}
        onApprove={() => void decide(() => approveCart(cartId))}
        onReject={(reason) => void decide(() => rejectCart(cartId, reason))}
      />
    </main>
  )
}
