import type { ReactElement } from 'react'

// The backend signs nothing yet and the UI has no verify call, so the mark never says signed.
const TRUST_MARK = 'Not signed (development)'

export function TrustMark(): ReactElement {
  return <p className="trust-mark">{TRUST_MARK}</p>
}
