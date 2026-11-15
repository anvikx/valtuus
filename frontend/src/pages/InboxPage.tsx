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
import { deliveryDays, money } from '../components/ResultScreen.tsx'
import { formatCount, formatDateTime, formatHourMinute, formatTimeLeft } from '../format.ts'
import { isSignedOut, redirectToLogin } from '../session.ts'

interface InboxData {
  readonly session: Session
  readonly carts: readonly Cart[]
  readonly mandate: Mandate | null
  // "Time left" counts from here, so a render never reads the clock.
  readonly loadedAt: Date
}

type LoadState =
  | { readonly kind: 'loading' }
  | { readonly kind: 'failed' }
  | { readonly kind: 'ready'; readonly data: InboxData }

type Tone = 'decide' | 'done' | 'deny' | 'muted'

interface Outcome {
  readonly word: string
  readonly tone: Tone
}

interface CartProps {
  readonly cart: Cart
}

interface WaitingProps {
  readonly carts: readonly Cart[]
  readonly now: Date
}

interface DecidedProps {
  readonly carts: readonly Cart[]
}

// Words only, never reason codes. The colour repeats the word, it is not the signal.
const OUTCOME: Readonly<Record<Exclude<CartStatus, 'waiting'>, Outcome>> = {
  ordered: { word: 'Ordered', tone: 'done' },
  rejected: { word: 'Rejected', tone: 'deny' },
  denied: { word: 'Denied', tone: 'deny' },
  expired: { word: 'Expired', tone: 'muted' },
  withdrawn: { word: 'Withdrawn', tone: 'muted' },
  closed: { word: 'Closed', tone: 'muted' },
}

const CURRENCY = 'EUR'
const EMPTY_SENTENCE =
  'Your agent orders inside your limits. When an order needs you, it appears here and the agent sends you the link.'

async function loadInbox(): Promise<InboxData> {
  // The session comes first, so a signed out user never gets a cart request.
  const session = await getSession()
  // The limits line only helps, so any mandate error just hides it. The cart list already
  // sends a signed out user to the login page.
  const [carts, mandate] = await Promise.all([listCarts(), getMandate().catch(() => null)])
  return {
    session,
    carts,
    mandate,
    loadedAt: new Date(),
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

function outcomeOf({ status }: Cart): Outcome {
  return OUTCOME[status as Exclude<CartStatus, 'waiting'>]
}

/** 1 gives "1 reason", 3 gives "3 reasons". */
function countOf(count: number, noun: string): string {
  return `${formatCount(count)} ${noun}${count === 1 ? '' : 's'}`
}

/** "Delivery Mon 16 Nov · 2 products" */
function waitingFacts({ lines }: Cart): string {
  const delivery = deliveryDays(lines)
  const products = countOf(lines.length, 'product')
  return delivery === '' ? products : `Delivery ${delivery} · ${products}`
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

// The list holds today's decisions only, so the time needs no date.
function decidedDetail(cart: Cart): string {
  const at = cart.decidedAt === null ? null : formatHourMinute(cart.decidedAt)
  return [ordererOrWhy(cart), at].filter((part) => part !== null && part !== '').join(', ')
}

// One amount when both limits match: "up to 500.00 EUR per order and per delivery day".
function limitsSentence({ maxOrder, maxPerDay, canAutoOrder }: Mandate): string {
  if (!canAutoOrder) {
    return 'Your agent orders nothing alone. You approve every cart.'
  }

  const perOrder = money(maxOrder, CURRENCY)
  const perDay =
    maxOrder === maxPerDay ? 'per delivery day' : `${money(maxPerDay, CURRENCY)} per delivery day`
  return `Your agent orders alone up to ${perOrder} per order and ${perDay}.`
}

function Dot({ tone }: { readonly tone: Tone }): ReactElement {
  return <span aria-hidden="true" className={`inbox-dot inbox-dot-${tone}`} />
}

function UpdatedTag({ cart }: CartProps): ReactElement | null {
  return cart.update === null ? null : <span className="inbox-updated">Updated</span>
}

// Phone: one stacked row per cart. Desktop shows the tables below instead.
function WaitingItem({ cart }: CartProps): ReactElement {
  return (
    <li className="inbox-item">
      <a className="inbox-row inbox-row-waiting" href={cartHref(cart)}>
        <span className="inbox-main">
          <span className="inbox-line">
            <span className="inbox-request">{cart.requestText}</span>
            <span className="inbox-total">{money(cart.total, cart.currency)}</span>
          </span>
          <span className="inbox-small muted">{waitingFacts(cart)}</span>
          <span className="inbox-small inbox-status">
            <Dot tone="decide" />
            {countOf(cart.reasons.length, 'reason')} · before {formatDateTime(cart.approveBefore)}
            <UpdatedTag cart={cart} />
          </span>
        </span>
        <Icon className="inbox-chevron" name="chevron" />
      </a>
    </li>
  )
}

function DecidedItem({ cart }: CartProps): ReactElement {
  const { word, tone } = outcomeOf(cart)

  return (
    <li className="inbox-item">
      <a className="inbox-row" href={cartHref(cart)}>
        <span className="inbox-main">
          <span className="inbox-line">
            <span className="inbox-request">{cart.requestText}</span>
            <span className="inbox-total">{money(cart.total, cart.currency)}</span>
          </span>
          <span className="inbox-small">
            <span className={`inbox-outcome inbox-outcome-${tone}`}>{word}.</span>{' '}
            <span className="muted">{decidedDetail(cart)}</span>
          </span>
        </span>
        <Icon className="inbox-chevron" name="chevron" />
      </a>
    </li>
  )
}

function RequestCell({ cart, detail }: CartProps & { readonly detail: string }): ReactElement {
  return (
    <td>
      <a className="inbox-cell-link" href={cartHref(cart)}>
        <span className="inbox-request">
          {cart.requestText}
          <UpdatedTag cart={cart} />
        </span>
        <span className="inbox-small muted inbox-clip">{detail}</span>
      </a>
    </td>
  )
}

function WaitingTable({ carts, now }: WaitingProps): ReactElement {
  return (
    <table aria-labelledby="inbox-waiting" className="inbox-table inbox-table-waiting">
      <thead>
        <tr>
          <th scope="col">Request</th>
          <th scope="col">Why it waits</th>
          <th scope="col">Time left</th>
          <th className="inbox-amount" scope="col">
            Total ex VAT
          </th>
        </tr>
      </thead>
      <tbody>
        {carts.map((cart) => (
          <tr key={cart.id}>
            <RequestCell cart={cart} detail={waitingFacts(cart)} />
            <td>
              <span className="inbox-status">
                <Dot tone="decide" />
                {countOf(cart.reasons.length, 'reason')}
              </span>
            </td>
            <td>
              <span className="inbox-time-left">{formatTimeLeft(cart.approveBefore, now)}</span>
              <span className="inbox-small muted">Before {formatDateTime(cart.approveBefore)}</span>
            </td>
            <td className="inbox-amount">{money(cart.total, cart.currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function DecidedTable({ carts }: DecidedProps): ReactElement {
  return (
    <table aria-labelledby="inbox-decided" className="inbox-table">
      <thead>
        <tr>
          <th scope="col">Request</th>
          <th scope="col">Status</th>
          <th scope="col">When</th>
          <th className="inbox-amount" scope="col">
            Total ex VAT
          </th>
        </tr>
      </thead>
      <tbody>
        {carts.map((cart) => {
          const { word, tone } = outcomeOf(cart)
          return (
            <tr key={cart.id}>
              <RequestCell cart={cart} detail={ordererOrWhy(cart) ?? ''} />
              <td>
                <span className="inbox-status">
                  <Dot tone={tone} />
                  {word}
                </span>
              </td>
              <td className="muted">
                {cart.decidedAt === null ? null : `Today ${formatHourMinute(cart.decidedAt)}`}
              </td>
              <td className="inbox-amount">{money(cart.total, cart.currency)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// Desktop only: the counts and the limits in one line under the title.
function Summary({
  waiting,
  decided,
  mandate,
}: {
  readonly waiting: number
  readonly decided: number
  readonly mandate: Mandate | null
}): ReactElement {
  return (
    <div className="inbox-summary">
      <dl className="inbox-summary-facts">
        <div>
          <dt>Wait for you</dt>
          <dd className="inbox-summary-waiting">{waiting}</dd>
        </div>
        <div>
          <dt>Decided today</dt>
          <dd>{decided}</dd>
        </div>
        {mandate === null || mandate.canAutoOrder ? null : (
          <div>
            <dt>Agent orders alone</dt>
            <dd>Off</dd>
          </div>
        )}
        {mandate === null || !mandate.canAutoOrder ? null : (
          <div>
            <dt>Agent orders alone up to</dt>
            <dd>{money(mandate.maxOrder, CURRENCY)}</dd>
          </div>
        )}
        {mandate === null ||
        !mandate.canAutoOrder ||
        mandate.maxPerDay === mandate.maxOrder ? null : (
          <div>
            <dt>Per delivery day</dt>
            <dd>{money(mandate.maxPerDay, CURRENCY)}</dd>
          </div>
        )}
      </dl>
      <a className="inbox-limits-link" href="/permissions">
        Agent permissions
      </a>
    </div>
  )
}

function WaitingSection({ carts, now }: WaitingProps): ReactElement {
  if (carts.length === 0) {
    return (
      <section aria-labelledby="inbox-waiting" className="inbox-section">
        <div className="inbox-empty">
          <h2 className="heading" id="inbox-waiting">
            Nothing waits for you
          </h2>
          <p>{EMPTY_SENTENCE}</p>
        </div>
      </section>
    )
  }

  return (
    <section aria-labelledby="inbox-waiting" className="inbox-section">
      <h2 className="heading" id="inbox-waiting">
        Waits for you <span className="inbox-count">({carts.length})</span>
      </h2>
      <ul className="inbox-list" role="list">
        {carts.map((cart) => (
          <WaitingItem cart={cart} key={cart.id} />
        ))}
      </ul>
      <WaitingTable carts={carts} now={now} />
      <p className="muted inbox-narrow">
        Prices are ex VAT. Open an order to approve, change or reject it.
      </p>
    </section>
  )
}

function DecidedSection({ carts }: DecidedProps): ReactElement | null {
  if (carts.length === 0) {
    return null
  }

  return (
    <section aria-labelledby="inbox-decided" className="inbox-section">
      <h2 className="heading" id="inbox-decided">
        Decided today <span className="inbox-count">({carts.length})</span>
      </h2>
      <ul className="inbox-list" role="list">
        {carts.map((cart) => (
          <DecidedItem cart={cart} key={cart.id} />
        ))}
      </ul>
      <DecidedTable carts={carts} />
    </section>
  )
}

// Phone rows and desktop tables are both in the page. CSS shows one of them, and the hidden one
// is display: none, so a screen reader and the Tab key meet only the one on screen.
function InboxView({ data }: { readonly data: InboxData }): ReactElement {
  const waiting = data.carts.filter((cart) => cart.status === 'waiting')
  const decided = data.carts.filter((cart) => cart.status !== 'waiting' && isToday(cart.decidedAt))

  return (
    <main className="inbox">
      <header className="inbox-head">
        <h1 className="page-title">Approvals</h1>
        <span className="muted">{data.session.buyerId} · Main user</span>
      </header>
      <Summary waiting={waiting.length} decided={decided.length} mandate={data.mandate} />
      <WaitingSection carts={waiting} now={data.loadedAt} />
      <DecidedSection carts={decided} />

      {data.mandate === null ? null : (
        <p className="muted inbox-limits inbox-narrow">
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
