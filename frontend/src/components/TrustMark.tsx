import type { ReactElement } from 'react'

import type { OrderTrust } from '../api.ts'

const UNVERIFIED_TEXT: Readonly<Record<Exclude<OrderTrust['kind'], 'verified'>, string>> = {
  unsigned: 'Not signed (development)',
  invalid: 'Signature check failed',
  unchecked: 'Signature could not be checked',
}

interface TrustMarkProps {
  // Not set before the order: only the order confirmation carries a signature.
  readonly trust?: OrderTrust
}

function trustText(trust: OrderTrust | undefined): string {
  if (trust === undefined) {
    return 'Not signed yet'
  }

  if (trust.kind === 'verified') {
    return `Signed by ${trust.issuer}, signature checked`
  }

  return UNVERIFIED_TEXT[trust.kind]
}

export function TrustMark({ trust }: TrustMarkProps): ReactElement {
  // A failed check means the shown order may not be what the seller signed, so it stands out.
  const className = trust?.kind === 'invalid' ? 'alert' : 'trust-mark'
  return <p className={className}>{trustText(trust)}</p>
}
