import type { ReactElement } from 'react'

import type { OfferTrust, OrderTrust } from '../api.ts'
import { formatDateTime } from '../format.ts'

const UNVERIFIED_TEXT: Readonly<Record<Exclude<OrderTrust['kind'], 'verified'>, string>> = {
  unsigned: 'Not signed (development)',
  invalid: 'Signature check failed',
  unchecked: 'Signature could not be checked',
}

// "mock issuer" on every signed mark: the prototype's key is not a real supplier's.
const SIGNED_BY = 'Signed by Valio Aimo (mock issuer)'

interface TrustMarkProps {
  // OfferTrust before the order, OrderTrust after it.
  readonly trust: OrderTrust | OfferTrust
}

function trustText(trust: OrderTrust | OfferTrust): string {
  if (trust.kind !== 'verified') {
    return UNVERIFIED_TEXT[trust.kind]
  }

  if ('stockAsOf' in trust) {
    return `${SIGNED_BY}. Price fixed. Stock as of ${formatDateTime(trust.stockAsOf)}, not reserved.`
  }

  return `${SIGNED_BY}, signature checked`
}

export function TrustMark({ trust }: TrustMarkProps): ReactElement {
  // A failed check means the shown order may not be what the seller signed, so it stands out.
  const className = trust.kind === 'invalid' ? 'alert' : 'trust-mark'
  return <p className={className}>{trustText(trust)}</p>
}
