import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'

import {
  ApiError,
  approveCart,
  changeCart,
  getAudit,
  getCart,
  getSession,
  rejectCart,
  type AuditTrail,
  type Cart,
  type CartChange,
  type Session,
} from '../api.ts'
import { AuditTimeline } from '../components/AuditTimeline.tsx'
import { CartReview, UPDATE_NOTE_ID } from '../components/CartReview.tsx'
import { DecisionPanel } from '../components/DecisionPanel.tsx'
import { OrderedResult } from '../components/OrderedResult.tsx'
import { ClosedResult } from '../components/ClosedResult.tsx'
import { UpdateBar } from '../components/UpdateBar.tsx'
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
// adds the agent name and the timeline: the page still works without it.
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
  const retryButton = useRef<HTMLButtonElement>(null)
  // The revision the user tapped Review on. A newer revision needs a new tap.
  const [reviewedRevision, setReviewedRevision] = useState<number | null>(null)
  // Set after a 409 or a saved change, until the user taps Review.
  const [shouldFocusReview, setShouldFocusReview] = useState(false)
  const reviewButton = useRef<HTMLButtonElement>(null)
  const [isNoteSent, setIsNoteSent] = useState(false)
  const noteSentLine = useRef<HTMLParagraphElement>(null)

  // The busy state disables the button that had focus, so focus falls to the page body.
  // Retry takes it once it is enabled, and a keyboard user can send the decision again.
  useEffect(() => {
    if (failedCall !== null && !isBusy) {
      retryButton.current?.focus()
    }
  }, [failedCall, isBusy])

  // Same focus loss after a 409 or a saved change: Review is the next step, so it takes the
  // focus. A note alone makes no new version and no bar, so the "sent" line takes it.
  useEffect(() => {
    if (!shouldFocusReview || isBusy) {
      return
    }

    const target = reviewButton.current ?? (isNoteSent ? noteSentLine.current : null)
    target?.focus()
  }, [shouldFocusReview, isNoteSent, isBusy])

  // The button that had focus leaves with the bar, so focus moves to the "Updated" line.
  useEffect(() => {
    if (reviewedRevision !== null) {
      document.getElementById(UPDATE_NOTE_ID)?.focus()
    }
  }, [reviewedRevision])

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
      setShouldFocusReview(true)
      await load()
      return
    }

    setFailedCall(() => call)
  }

  async function sendChange(revision: number, change: CartChange): Promise<void> {
    await changeCart(cartId, revision, change)
    setShouldFocusReview(true)
    setIsNoteSent(change.note.trim() !== '')
  }

  async function decide(call: DecisionCall): Promise<void> {
    if (isBusyRef.current) {
      return
    }

    isBusyRef.current = true
    setIsBusy(true)
    setFailedCall(null)
    setIsNoteSent(false)
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

  const { session, cart: latest, audit } = state.data
  const { update } = latest
  // Only a waiting cart holds the old version back. A decided cart shows what was decided, even
  // after a reload resets reviewedRevision.
  const isReviewPending =
    latest.status === 'waiting' && update !== null && reviewedRevision !== latest.revision
  // Until Review, the user keeps the version they were reading. A decision names that version.
  const cart =
    update !== null && isReviewPending
      ? {
          ...latest,
          lines: update.previousLines,
          total: update.previousTotal,
          deliveryDayTotal: update.previousDeliveryDayTotal,
          reasons: update.previousReasons,
        }
      : latest
  const timeline = (
    <AuditTimeline
      cartId={cartId}
      audit={audit}
      requestText={cart.requestText}
      status={cart.status}
      initialState={cart.status === 'waiting' ? 'collapsed' : 'open'}
    />
  )
  if (cart.status === 'ordered') {
    return (
      <main className="stack">
        <OrderedResult cart={cart} />
        {timeline}
      </main>
    )
  }

  if (cart.status !== 'waiting') {
    return (
      <main className="stack">
        <ClosedResult cart={cart} status={cart.status} />
        {timeline}
      </main>
    )
  }

  return (
    <main className="approval">
      <div className="approval-main">
        {isReviewPending ? (
          <UpdateBar
            ref={reviewButton}
            onReview={() => {
              setShouldFocusReview(false)
              setReviewedRevision(latest.revision)
            }}
          />
        ) : null}
        <CartReview
          cart={cart}
          buyerId={session.buyerId}
          agentName={audit?.agentName ?? null}
          update={isReviewPending ? undefined : (update ?? undefined)}
        />
        {timeline}
      </div>
      <aside className="decision" aria-label="Decision">
        {failedCall === null ? null : (
          <div className="stack-tight">
            <p className="alert" role="alert">
              Your decision was not saved.
            </p>
            <button
              className="button button-primary"
              type="button"
              ref={retryButton}
              disabled={isBusy}
              onClick={() => void decide(failedCall)}
            >
              Retry
            </button>
          </div>
        )}
        {isNoteSent ? (
          <p className="muted" ref={noteSentLine} role="status" tabIndex={-1}>
            Your note was sent to the agent. Its update shows on this page.
          </p>
        ) : null}
        <DecisionPanel
          cart={cart}
          isBusy={isBusy}
          isReviewPending={isReviewPending}
          update={isReviewPending ? undefined : (update ?? undefined)}
          onApprove={() => void decide(() => approveCart(cartId, latest.revision))}
          onReject={(reason) => void decide(() => rejectCart(cartId, latest.revision, reason))}
          onChange={(change: CartChange) => void decide(() => sendChange(latest.revision, change))}
        />
      </aside>
    </main>
  )
}
