import type { ReactElement } from 'react'

import type { Cart, CartStatus } from '../api.ts'
import { formatDateTime } from '../format.ts'
import { FlowSteps, type StopTone } from './FlowSteps.tsx'
import type { IconName } from './Icon.tsx'
import { ResultScreen } from './ResultScreen.tsx'

// An ordered cart shows OrderedResult instead.
type ClosedStatus = Exclude<CartStatus, 'waiting' | 'ordered'>

interface ClosedResultProps {
  readonly cart: Cart
  readonly status: ClosedStatus
}

interface ClosedView {
  readonly tone: StopTone
  readonly icon: IconName
  readonly title: string
  readonly sentence: (cart: Cart) => string
  readonly detail?: (cart: Cart) => string
  readonly deliveryNote?: string
}

// A cart in AUTO state is not specified for this page.
const CLOSED_SENTENCE = 'This order needs no decision from you.'
const EXPIRED_FALLBACK = 'Nobody decided before the order deadline.'
const DENIED_FALLBACK = 'The rules do not allow this order. Nothing was ordered.'
const WITHDRAWN_SENTENCE = 'The buyer cancelled this order. Nothing was ordered.'
const NO_ORDER_DETAIL = 'No order was placed.'

// "by main user of hotel-1 at Sat 14 Nov 10:04", or less when the cart leaves a field empty.
function decidedText({ decidedBy, decidedAt }: Cart): string {
  const by = decidedBy === null ? '' : ` by ${decidedBy}`
  const at = decidedAt === null ? '' : ` at ${formatDateTime(decidedAt)}`
  return `${by}${at}`
}

function reasonsText({ reasons }: Cart, fallback: string): string {
  return reasons.length === 0 ? fallback : reasons.join(' ')
}

const CLOSED_VIEWS: Readonly<Record<ClosedStatus, ClosedView>> = {
  rejected: {
    tone: 'deny',
    icon: 'cross',
    title: 'Order rejected',
    sentence: (cart) => `Rejected${decidedText(cart)}:`,
    detail: ({ rejectReason }) => `"${rejectReason ?? 'No reason given'}"`,
  },
  expired: {
    tone: 'muted',
    icon: 'clock',
    title: 'Order expired',
    sentence: (cart) => reasonsText(cart, EXPIRED_FALLBACK),
    detail: () => NO_ORDER_DETAIL,
    deliveryNote: 'no longer possible',
  },
  denied: {
    tone: 'deny',
    icon: 'cross',
    title: 'Order denied',
    sentence: (cart) => reasonsText(cart, DENIED_FALLBACK),
  },
  withdrawn: {
    tone: 'muted',
    icon: 'minus',
    title: 'Order withdrawn',
    sentence: () => WITHDRAWN_SENTENCE,
  },
  closed: {
    tone: 'muted',
    icon: 'minus',
    title: 'Order closed',
    sentence: () => CLOSED_SENTENCE,
  },
}

// A cart that is no longer waiting and was not ordered. No buttons: nothing is left to decide.
export function ClosedResult({ cart, status }: ClosedResultProps): ReactElement {
  const { tone, icon, title, sentence, detail, deliveryNote } = CLOSED_VIEWS[status]

  // Only a closed cart shows the steps: they mark where the flow stopped. An ordered cart
  // finished every step, so the steps tell the reader nothing new.
  return (
    <>
      <FlowSteps currentPhase={null} stopTone={tone} />
      <ResultScreen
        cart={cart}
        tone={tone}
        icon={icon}
        title={title}
        sentence={sentence(cart)}
        detail={detail?.(cart)}
        deliveryNote={deliveryNote}
      />
    </>
  )
}
