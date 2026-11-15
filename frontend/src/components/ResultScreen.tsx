import { useEffect, useRef, type ReactElement, type ReactNode } from 'react'

import {
  offerFactsKey,
  type Cart,
  type CartLine,
  type CartUpdate,
  type LineStock,
  type OfferFactsByLine,
} from '../api.ts'
import { formatCount, formatDate } from '../format.ts'
import type { StopTone } from './FlowSteps.tsx'
import { Icon, type IconName } from './Icon.tsx'
import { LineFacts } from './LineFacts.tsx'

export type ResultTone = 'done' | StopTone

interface CartProps {
  readonly cart: Cart
}

interface OrderLinesProps extends CartProps {
  // Marks what changed against the version the user saw before.
  readonly update?: CartUpdate
  // Missing for a line whose offer could not be read: the line then shows no facts row.
  readonly facts?: OfferFactsByLine
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
    </dl>
  )
}

// The old quantity struck through, then the new one. The struck text says "was" for a screen
// reader, which does not announce strikethrough.
function stockWords(stock: LineStock): string {
  switch (stock.kind) {
    case 'in-stock':
      return 'In stock'
    case 'unconfirmed':
      return 'Stock not confirmed'
    case 'short':
      return `Only ${formatCount(stock.available)} in stock`
  }
}

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

// The substitute against the requested product, per sales unit: "+0.04 EUR each".
function differenceWords(difference: string, currency: string): string {
  if (Number(difference) === 0) {
    return 'same price'
  }

  const sign = difference.startsWith('-') ? '' : '+'
  return `${sign}${money(difference, currency)} each`
}

// The requested name struck through. The struck text says "not delivered" for a screen reader,
// which does not announce strikethrough.
function ReplacedProduct({ name }: { name: string }): ReactElement {
  return (
    <p className="muted">
      In place of <s>{name}</s>
      <span className="sr-only"> not delivered</span>
    </p>
  )
}

function removedNames(cart: Cart, update: CartUpdate): string[] {
  const keptIds = new Set(cart.lines.map((line) => line.productId))
  return update.previousLines
    .filter((line) => !keptIds.has(line.productId))
    .map((line) => line.name)
}

export function OrderLines({ cart, update, facts }: OrderLinesProps): ReactElement {
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
          const substitution = line.substituteFor

          return (
            <li className="order-line" key={line.productId}>
              {substitution === null ? null : <ReplacedProduct name={substitution.requestedName} />}
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
                {substitution === null
                  ? null
                  : ` · ${differenceWords(substitution.priceDifference, cart.currency)}`}
              </p>
              <p className="muted">{stockWords(line.stock)}</p>
              {/* The reason says "this product" for the requested one, so it names it first. */}
              {substitution === null ? null : (
                <p className="line-reason">
                  {substitution.requestedName}: {substitution.reason}
                </p>
              )}
              <LineFacts facts={facts?.get(offerFactsKey(line))} />
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
      {/* Nothing is left to decide here, so the next step is the inbox. */}
      <a className="result-back" href="/inbox">
        Back to approvals
      </a>
    </>
  )
}
