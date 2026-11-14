import { useEffect, useRef, type ReactElement } from 'react'

import type { Cart, CartStatus } from '../api.ts'
import { formatDateTime } from '../format.ts'
import { Icon, type IconName } from './Icon.tsx'

type ClosedStatus = Exclude<CartStatus, 'waiting'>

const RESULT_ICON: Readonly<Record<ClosedStatus, IconName>> = {
  ordered: 'done',
  rejected: 'denied',
  expired: 'clock',
  closed: 'attention',
}

const PROTOTYPE_ORDER_NOTE =
  "Prototype order: committed in this prototype's order ledger, not sent to Valio Aimo's production systems."

// A cart in AUTO or DENIED state is not specified for this page (open question 9).
const CLOSED_SENTENCE = 'This order needs no decision from you.'
const EXPIRED_FALLBACK = 'Nobody decided before the order deadline.'

interface ResultCardProps {
  readonly cart: Cart
  readonly status: ClosedStatus
}

// "by main user of hotel-1 at Sat 14 Nov 10:04", or less when the cart leaves a field empty.
function decidedText({ decidedBy, decidedAt }: Cart): string {
  const by = decidedBy === null ? '' : ` by ${decidedBy}`
  const at = decidedAt === null ? '' : ` at ${formatDateTime(decidedAt)}`
  return `${by}${at}`
}

function resultSentence(cart: Cart, status: ClosedStatus): string {
  if (status === 'ordered') {
    const order = cart.orderId === null ? 'order' : `order ${cart.orderId}`
    const amount = `${cart.total} ${cart.currency} ex VAT`
    // No approver: the agent's checkout placed it under the rules, for example after a limit raise.
    if (cart.decidedBy === null) {
      return `Ordered with no approval needed: ${order}, ${amount}.`
    }

    return `Approved${decidedText(cart)}: ${order}, ${amount}.`
  }

  if (status === 'rejected') {
    return `Rejected${decidedText(cart)}: ${cart.rejectReason ?? 'no reason given'}`
  }

  if (status === 'expired') {
    return cart.reasons.length === 0 ? EXPIRED_FALLBACK : cart.reasons.join(' ')
  }

  return CLOSED_SENTENCE
}

// One icon and one sentence for a cart that is no longer waiting. No buttons: nothing is
// left to decide.
export function ResultCard({ cart, status }: ResultCardProps): ReactElement {
  const heading = useRef<HTMLHeadingElement>(null)

  // The card replaces the buttons after a decision. Focus moves to its sentence, so a screen
  // reader reads the outcome and keyboard focus is not lost.
  useEffect(() => {
    heading.current?.focus()
  }, [])

  return (
    <section className={`card result result-${status}`}>
      <Icon className="result-icon" name={RESULT_ICON[status]} />
      <h1 className="heading" ref={heading} tabIndex={-1}>
        {resultSentence(cart, status)}
      </h1>
      {status === 'ordered' ? <p className="muted">{PROTOTYPE_ORDER_NOTE}</p> : null}
    </section>
  )
}
