import { useEffect, useRef, type ReactElement, type ReactNode } from 'react'

import type { Cart, CartLine, CartUpdate } from '../api.ts'
import { formatCount, formatDate } from '../format.ts'
import { FlowSteps, type StopTone } from './FlowSteps.tsx'
import { Icon, type IconName } from './Icon.tsx'

export type ResultTone = 'done' | StopTone

interface CartProps {
  readonly cart: Cart
}

interface OrderLinesProps extends CartProps {
  // Marks what changed against the version the user saw before.
  readonly update?: CartUpdate
}

interface ResultScreenProps extends CartProps {
  readonly tone: ResultTone
  readonly icon: IconName
  readonly title: string
  readonly sentence: string
  // A muted line under the sentence, for example the rejection reason.
  readonly detail?: string
  // Added after the delivery day, for example "no longer possible" on an expired cart.
  readonly deliveryNote?: string
  readonly children?: ReactNode
}

export function money(amount: string, currency: string): string {
  return `${amount} ${currency}`
}

// One date for most carts. Lines with different delivery days list each day once.
export function deliveryDays(lines: readonly CartLine[]): string {
  return [...new Set(lines.map((line) => line.deliveryDate))].map(formatDate).join(', ')
}

function SummaryRows({
  cart,
  deliveryNote,
}: CartProps & { readonly deliveryNote?: string }): ReactElement {
  const delivery = deliveryDays(cart.lines)

  return (
    <dl className="summary-rows">
      <div className="summary-row">
        <dt>Total</dt>
        <dd>
          <strong>{money(cart.total, cart.currency)}</strong> <span className="muted">ex VAT</span>
        </dd>
      </div>
      {delivery === '' ? null : (
        <div className="summary-row">
          <dt>Delivery</dt>
          <dd>{deliveryNote === undefined ? delivery : `${delivery}, ${deliveryNote}`}</dd>
        </div>
      )}
      {cart.orderId === null ? null : (
        <div className="summary-row">
          <dt>Order</dt>
          <dd>{cart.orderId}</dd>
        </div>
      )}
    </dl>
  )
}

// The old quantity struck through, then the new one. The struck text says "was" for a screen
// reader, which does not announce strikethrough.
function Quantity({ line, before }: { line: CartLine; before?: CartLine }): ReactElement {
  if (before === undefined || before.qty === line.qty) {
    return <>{formatCount(line.qty)}</>
  }

  return (
    <>
      <s>{formatCount(before.qty)}</s>
      <span className="sr-only"> was {formatCount(before.qty)}</span>{' '}
      <mark className="change-mark">{formatCount(line.qty)}</mark>
    </>
  )
}

function removedNames(cart: Cart, update: CartUpdate): string[] {
  const keptIds = new Set(cart.lines.map((line) => line.productId))
  return update.previousLines
    .filter((line) => !keptIds.has(line.productId))
    .map((line) => line.name)
}

export function OrderLines({ cart, update }: OrderLinesProps): ReactElement {
  const removed = update === undefined ? [] : removedNames(cart, update)

  return (
    <section className="stack-tight" aria-labelledby="order-lines-title">
      <h2 className="heading" id="order-lines-title">
        Order
      </h2>
      <ul className="order-lines">
        {cart.lines.map((line) => {
          const before = update?.previousLines.find((old) => old.productId === line.productId)
          const unitPrice = money(line.unitPrice, cart.currency)

          return (
            <li className="order-line" key={line.productId}>
              <div className="line-head">
                <strong>
                  {line.name}
                  {update !== undefined && before === undefined ? (
                    <span className="change-mark change-new">New</span>
                  ) : null}
                </strong>
                <strong>{money(line.lineTotal, cart.currency)}</strong>
              </div>
              <p className="muted">
                <Quantity line={line} before={before} /> × {unitPrice} ex VAT
              </p>
            </li>
          )
        })}
      </ul>
      {removed.length === 0 ? null : <p className="muted">Removed: {removed.join(', ')}</p>}
    </section>
  )
}

// The head, summary and lines that an ordered cart and a closed cart share.
export function ResultScreen({
  cart,
  tone,
  icon,
  title,
  sentence,
  detail,
  deliveryNote,
  children,
}: ResultScreenProps): ReactElement {
  const heading = useRef<HTMLHeadingElement>(null)

  // The result replaces the buttons after a decision. Focus moves to its title, so a screen
  // reader reads the outcome and keyboard focus is not lost.
  useEffect(() => {
    heading.current?.focus()
  }, [])

  return (
    <>
      <FlowSteps currentPhase={null} stopTone={tone === 'done' ? undefined : tone} />
      <section className="result-head">
        <span className={`result-badge result-badge-${tone}`}>
          <Icon name={icon} />
        </span>
        <h1 className="title" ref={heading} tabIndex={-1}>
          {title}
        </h1>
        <p>{sentence}</p>
        {detail === undefined ? null : <p className="muted">{detail}</p>}
      </section>
      <SummaryRows cart={cart} deliveryNote={deliveryNote} />
      <OrderLines cart={cart} />
      {children}
    </>
  )
}
