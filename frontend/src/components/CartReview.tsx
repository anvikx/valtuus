import type { ReactElement } from 'react'

import type { Cart, CartUpdate, OfferFactsByLine, OfferTrust, UnderstoodRequest } from '../api.ts'
import {
  formatAttribute,
  formatCount,
  formatDate,
  formatDateTime,
  formatHourMinute,
} from '../format.ts'
import { FlowSteps } from './FlowSteps.tsx'
import { OrderLines, deliveryDays, money } from './ResultScreen.tsx'
import { TrustMark } from './TrustMark.tsx'

export const UPDATE_NOTE_ID = 'update-note'

interface CartReviewProps {
  readonly cart: Cart
  readonly buyerId: string
  readonly agentName: string | null
  readonly trust: OfferTrust
  readonly facts: OfferFactsByLine
  // Set once the user has reviewed the update: it turns on the change marks.
  readonly update?: CartUpdate
}

interface ApprovalSummaryProps {
  readonly cart: Cart
  readonly update?: CartUpdate
}

function understoodParts(understood: UnderstoodRequest | null): string[] {
  if (understood === null) {
    return []
  }

  const { quantity, unit, attributes, deliverBy } = understood
  const parts = attributes.map(formatAttribute)
  if (quantity !== null) {
    parts.unshift(unit === null ? formatCount(quantity) : `${formatCount(quantity)} ${unit}`)
  }

  if (deliverBy !== null) {
    parts.push(`By ${formatDate(deliverBy)}`)
  }

  return parts
}

export function ApprovalSummary({ cart, update }: ApprovalSummaryProps): ReactElement {
  const delivery = deliveryDays(cart.lines)

  return (
    <div className="stack">
      <dl className="summary-rows">
        <div className="summary-row">
          <dt>Total</dt>
          <dd>
            <strong className="summary-total">{money(cart.total, cart.currency)}</strong>{' '}
            <span className="muted">ex VAT</span>
            {update === undefined ? null : (
              <span className="summary-was muted">
                <s>{money(update.previousTotal, cart.currency)}</s>
                <span className="sr-only"> was {money(update.previousTotal, cart.currency)}</span>
              </span>
            )}
          </dd>
        </div>
        <div className="summary-row">
          <dt>Approve before</dt>
          <dd className="summary-deadline">{formatDateTime(cart.approveBefore)}</dd>
        </div>
        {delivery === '' ? null : (
          <div className="summary-row">
            <dt>Delivery</dt>
            <dd>{delivery}</dd>
          </div>
        )}
      </dl>
      {/* A string compare, not arithmetic: equal means no other automatic orders that day. */}
      {cart.deliveryDayTotal === cart.total ? null : (
        <p className="muted">
          With the automatic orders for the same delivery day:{' '}
          {money(cart.deliveryDayTotal, cart.currency)} ex VAT
        </p>
      )}
    </div>
  )
}

function WhyItWaits({ reasons }: { reasons: readonly string[] }): ReactElement | null {
  if (reasons.length === 0) {
    return null
  }

  return (
    <section className="why-waits" aria-labelledby="why-waits-title">
      <h2 className="why-waits-title" id="why-waits-title">
        Why it waits for you
      </h2>
      {reasons.length === 1 ? (
        <p>{reasons[0]}</p>
      ) : (
        <ul className="why-waits-list">
          {reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

function RequestSection({ cart }: { cart: Cart }): ReactElement {
  const parts = understoodParts(cart.understood)

  return (
    <section className="stack-tight" aria-labelledby="request-title">
      <h2 className="heading" id="request-title">
        Request
      </h2>
      <p>&ldquo;{cart.requestText}&rdquo;</p>
      {parts.length === 0 ? null : <p className="muted">Understood as {parts.join(' · ')}</p>}
      {cart.clarifications.length === 0 ? null : (
        <ol className="stack-tight clarifications" aria-label="Questions and answers">
          {cart.clarifications.map((text, index) => (
            <li key={index}>{text}</li>
          ))}
        </ol>
      )}
    </section>
  )
}

// Everything the main user needs to decide on a waiting cart, top to bottom as in the UI spec.
export function CartReview({
  cart,
  buyerId,
  agentName,
  trust,
  facts,
  update,
}: CartReviewProps): ReactElement {
  return (
    <>
      <FlowSteps currentPhase="approval" />
      <header className="stack-tight">
        <h1 className="title">Approve this order?</h1>
        <p className="muted">
          {buyerId} &middot; {agentName === null ? 'agent not known' : `from ${agentName}`}
        </p>
        {update === undefined ? null : (
          <p className="update-note" id={UPDATE_NOTE_ID} tabIndex={-1}>
            Updated {formatHourMinute(update.at)} by {update.by}: {update.summary}.
          </p>
        )}
      </header>
      <WhyItWaits reasons={cart.reasons} />
      <div className="phone-only">
        <ApprovalSummary cart={cart} update={update} />
      </div>
      <OrderLines cart={cart} update={update} facts={facts} />
      <div className="phone-only">
        <TrustMark trust={trust} />
      </div>
      <RequestSection cart={cart} />
    </>
  )
}
