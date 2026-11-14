import { useCallback, useEffect, useState, type ReactElement } from 'react'

import {
  getMandate,
  getSession,
  listCarts,
  type Cart,
  type CartStatus,
  type Mandate,
  type Session,
} from '../api.ts'
import { Icon } from '../components/Icon.tsx'
import { money } from '../components/ResultScreen.tsx'
import { formatDateTime } from '../format.ts'
import { isSignedOut, redirectToLogin } from '../session.ts'

interface InboxData {
  readonly session: Session
  readonly carts: readonly Cart[]
  readonly mandate: Mandate | null
}

type LoadState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed' }
  | { readonly kind: 'ready'; readonly data: InboxData }

interface Outcome {
  readonly word: string
  readonly tone: 'done' | 'deny' | 'muted'
}

// Words only, never reason codes. The colour repeats the word, it is not the signal.
const OUTCOME: Readonly<Record<Exclude<CartStatus, 'waiting'>, Outcome>> = {
  ordered: { word: 'Ordered.', tone: 'done' },
  rejected: { word: 'Rejected.', tone: 'deny' },
  denied: { word: 'Denied.', tone: 'deny' },
  expired: { word: 'Expired.', tone: 'muted' },
  withdrawn: { word: 'Withdrawn.', tone: 'muted' },
  closed: { word: 'Closed.', tone: 'muted' },
}

const CURRENCY = 'EUR'
const EMPTY_SENTENCE =
  'Your agent orders inside your limits. When an order needs you, it appears here and the agent sends you the link.'

async function loadInbox(): Promise<InboxData> {
  // The session comes first, so a signed out user never gets a cart request.
  const session = await getSession()
  // The limits line only helps, so any mandate error just hides it. Even a 401 is not a sign
  // out here: the real backend answers 401 to the main user on this route (see getMandate), and
  // a redirect would loop back to the login page after every sign in.
  const [carts, mandate] = await Promise.all([listCarts(), getMandate().catch(() => null)])
  return {
    session,
    carts,
    mandate,
  }
}

// Local time: "today" is the user's day, not the server's.
function isToday(value: string | null): boolean {
  if (value === null) {
    return false
  }

  return new Date(value).toDateString() === new Date().toDateString()
}

function cartHref({ id }: Cart): string {
  return `/carts/${encodeURIComponent(id)}`
}

function decidedDetail(cart: Cart): string {
  const at = cart.decidedAt === null ? null : formatDateTime(cart.decidedAt)
  return [ordererOrWhy(cart), at].filter((part) => part !== null && part !== '').join(', ')
}

// An ordered cart keeps the reason it once waited for ("over the limit"). Shown after
// "Ordered." it reads as a broken rule, so the line says who placed the order instead.
function ordererOrWhy(cart: Cart): string | null {
  if (cart.status === 'ordered') {
    return cart.decidedBy === null
      ? 'Placed by the agent inside your limits'
      : `Approved by ${cart.decidedBy}`
  }

  return cart.status === 'rejected' ? cart.rejectReason : (cart.reasons[0] ?? null)
}

// One amount when both limits match: "up to 500.00 EUR per order and per delivery day".
function limitsSentence({ maxOrder, maxPerDay }: Mandate): string {
  const perOrder = money(maxOrder, CURRENCY)
  const perDay =
    maxOrder === maxPerDay ? 'per delivery day' : `${money(maxPerDay, CURRENCY)} per delivery day`
  return `Your agent orders alone up to ${perOrder} per order and ${perDay}.`
}

function WaitingRow({ cart }: { readonly cart: Cart }): ReactElement {
  const [first, ...others] = cart.reasons

  return (
    <li className="inbox-item">
      <a className="inbox-row inbox-row-waiting" href={cartHref(cart)}>
        <span className="inbox-request">{cart.requestText}</span>
        <span className="inbox-total">{money(cart.total, cart.currency)}</span>
        <span className="inbox-why">
          {first}
          {others.length === 0 ? null : (
            <span className="inbox-more">
              {' '}
              +{others.length} more {others.length === 1 ? 'reason' : 'reasons'}
            </span>
          )}
        </span>
        <span className="inbox-deadline">Approve before {formatDateTime(cart.approveBefore)}</span>
        <Icon className="inbox-chevron" name="chevron" />
      </a>
    </li>
  )
}

function DecidedRow({ cart }: { readonly cart: Cart }): ReactElement {
  const { word, tone } = OUTCOME[cart.status as Exclude<CartStatus, 'waiting'>]

  return (
    <li className="inbox-item">
      <a className="inbox-row inbox-row-decided" href={cartHref(cart)}>
        <span className="inbox-request">{cart.requestText}</span>
        <span className="inbox-total">{money(cart.total, cart.currency)}</span>
        <span className="inbox-result">
          <span className={`inbox-outcome inbox-outcome-${tone}`}>{word}</span>{' '}
          <span className="muted">{decidedDetail(cart)}</span>
        </span>
        <Icon className="inbox-chevron" name="chevron" />
      </a>
    </li>
  )
}

function InboxView({ data }: { readonly data: InboxData }): ReactElement {
  const waiting = data.carts.filter((cart) => cart.status === 'waiting')
  const decided = data.carts.filter((cart) => cart.status !== 'waiting' && isToday(cart.decidedAt))

  return (
    <main className="inbox">
      <header className="inbox-head">
        <h1 className="page-title">Approvals</h1>
        <span className="muted">{data.session.buyerId} · Main user</span>
      </header>

      <section aria-labelledby="inbox-waiting" className="inbox-section">
        {waiting.length === 0 ? (
          <div className="inbox-empty">
            <h2 className="heading" id="inbox-waiting">
              Nothing waits for you
            </h2>
            <p>{EMPTY_SENTENCE}</p>
          </div>
        ) : (
          <>
            <h2 className="heading" id="inbox-waiting">
              Waits for you <span className="inbox-count">({waiting.length})</span>
            </h2>
            <ul className="inbox-list" role="list">
              {waiting.map((cart) => (
                <WaitingRow cart={cart} key={cart.id} />
              ))}
            </ul>
            <p className="muted">
              Prices are ex VAT. Open an order to approve, change or reject it.
            </p>
          </>
        )}
      </section>

      {decided.length === 0 ? null : (
        <section aria-labelledby="inbox-decided" className="inbox-section">
          <h2 className="heading" id="inbox-decided">
            Decided today
          </h2>
          <ul className="inbox-list" role="list">
            {decided.map((cart) => (
              <DecidedRow cart={cart} key={cart.id} />
            ))}
          </ul>
        </section>
      )}

      {data.mandate === null ? null : (
        <p className="muted inbox-limits">
          {limitsSentence(data.mandate)}{' '}
          <a className="inbox-limits-link" href="/permissions">
            Agent permissions
          </a>
        </p>
      )}
    </main>
  )
}

// Carts that wait for the main user.
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
          Loading the orders.
        </p>
      </main>
    )
  }

  if (state.kind === 'failed') {
    return (
      <main className="stack">
        <p className="alert" role="alert">
          The orders could not be loaded.
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

  return <InboxView data={state.data} />
}
