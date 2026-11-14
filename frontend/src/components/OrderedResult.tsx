import type { ReactElement } from 'react'

import type { Cart, OrderTrust } from '../api.ts'
import { formatDateTime } from '../format.ts'
import { ResultScreen } from './ResultScreen.tsx'
import { TrustMark } from './TrustMark.tsx'

const PROTOTYPE_ORDER_NOTE =
  "Prototype order: committed in this prototype's order ledger, not sent to Valio Aimo's production systems."

interface OrderedResultProps {
  readonly cart: Cart
  readonly trust: OrderTrust
}

// No approver: the agent's checkout placed it under the rules, for example after a limit raise.
function decisionSentence({ decidedBy, decidedAt }: Cart): string {
  if (decidedBy === null) {
    return 'Ordered with no approval needed.'
  }

  const at = decidedAt === null ? '' : ` at ${formatDateTime(decidedAt)}`
  return `Approved by ${decidedBy}${at}. The agent tells the buyer.`
}

// The order confirmation the main user sees after an approval, or on a reload of an ordered cart.
export function OrderedResult({ cart, trust }: OrderedResultProps): ReactElement {
  return (
    <ResultScreen
      cart={cart}
      tone="done"
      icon="check"
      title="Order placed"
      sentence={decisionSentence(cart)}
    >
      <TrustMark trust={trust} />
      <p className="muted">{PROTOTYPE_ORDER_NOTE}</p>
    </ResultScreen>
  )
}
