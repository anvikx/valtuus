import type { ReactElement } from 'react'

import type { Cart, CartLine, UnderstoodRequest } from '../api.ts'
import { formatAttribute, formatCount, formatDate, formatDateTime } from '../format.ts'
import { Icon } from './Icon.tsx'

// The cart has no signature field and the UI has no verify call yet.
const TRUST_MARK = 'Not signed (development)'

interface CartReviewProps {
  readonly cart: Cart
  readonly buyerId: string
  readonly agentName: string | null
}

function money(amount: string, currency: string): string {
  return `${amount} ${currency}`
}

function requestChips(understood: UnderstoodRequest | null): string[] {
  if (understood === null) {
    return []
  }

  const { quantity, unit, attributes, deliverBy } = understood
  const chips = attributes.map(formatAttribute)
  if (quantity !== null) {
    chips.unshift(unit === null ? formatCount(quantity) : `${formatCount(quantity)} ${unit}`)
  }

  if (deliverBy !== null) {
    chips.push(`By ${formatDate(deliverBy)}`)
  }

  return chips
}

function LineCard({ line, currency }: { line: CartLine; currency: string }): ReactElement {
  return (
    <li className="card line-card">
      <div className="line-head">
        <h3 className="heading">{line.name}</h3>
        <p className="heading">{money(line.lineTotal, currency)} ex VAT</p>
      </div>
      <p className="muted">Product {line.productId}</p>
      <p>
        {formatCount(line.qty)} x {money(line.unitPrice, currency)} ex VAT
      </p>
      <p className="muted">Delivery {formatDate(line.deliveryDate)}</p>
    </li>
  )
}

// Everything the main user needs to decide on a waiting cart, top to bottom as in the UI spec.
export function CartReview({ cart, buyerId, agentName }: CartReviewProps): ReactElement {
  const chips = requestChips(cart.understood)

  return (
    <>
      <header className="stack-tight">
        <h1 className="page-title">Approval needed</h1>
        <dl className="facts">
          <dt>Buyer</dt>
          <dd>{buyerId}</dd>
          <dt>Cart</dt>
          <dd>{cart.id}</dd>
          <dt>Agent</dt>
          <dd>{agentName ?? 'Not known'}</dd>
        </dl>
      </header>

      <blockquote className="quote">{cart.requestText}</blockquote>

      {cart.clarifications.length === 0 ? null : (
        <section className="stack-tight" aria-labelledby="clarifications-title">
          <h2 className="label" id="clarifications-title">
            Questions and answers
          </h2>
          <ol className="stack-tight">
            {cart.clarifications.map((text, index) => (
              <li key={index}>{text}</li>
            ))}
          </ol>
        </section>
      )}

      {chips.length === 0 ? null : (
        <section className="stack-tight" aria-labelledby="understood-title">
          <h2 className="label" id="understood-title">
            Understood as
          </h2>
          <ul className="chips">
            {chips.map((chip) => (
              <li className="chip" key={chip}>
                {chip}
              </li>
            ))}
          </ul>
        </section>
      )}

      {cart.reasons.map((reason) => (
        <p className="banner" key={reason}>
          <Icon className="banner-icon" name="attention" />
          {reason}
        </p>
      ))}

      <section className="stack-tight" aria-labelledby="lines-title">
        <h2 className="label" id="lines-title">
          Order lines
        </h2>
        <ul className="stack-tight">
          {cart.lines.map((line) => (
            <LineCard key={line.productId} line={line} currency={cart.currency} />
          ))}
        </ul>
      </section>

      <section className="card total" aria-label="Total">
        <p className="label">Total</p>
        <p>
          <span className="title">{money(cart.total, cart.currency)}</span> ex VAT
        </p>
        {/* A string compare, not arithmetic: equal means no other automatic orders that day. */}
        {cart.deliveryDayTotal === cart.total ? null : (
          <p>
            With the automatic orders for the same delivery day:{' '}
            {money(cart.deliveryDayTotal, cart.currency)} ex VAT
          </p>
        )}
        <p>Approve before {formatDateTime(cart.approveBefore)}</p>
      </section>

      <p className="trust-mark">{TRUST_MARK}</p>
    </>
  )
}
