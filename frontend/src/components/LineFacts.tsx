import type { ReactElement } from 'react'

import type { OfferFacts } from '../api.ts'
import { formatKg, formatLabel, formatPercent } from '../format.ts'

const NO_DATA = 'No data'

interface LineFactsProps {
  // undefined: the offer could not be read, so the row stays out.
  readonly facts: OfferFacts | undefined
}

// null stays "No data": 0 % reliability or 0 kg CO2e would be a claim the data does not make.
export function LineFacts({ facts }: LineFactsProps): ReactElement | null {
  if (facts === undefined) {
    return null
  }

  const { deliveryReliability, co2KgPerKg, labels } = facts

  return (
    <dl className="line-facts muted">
      <div>
        <dt>Delivery reliability</dt>
        <dd>{deliveryReliability === null ? NO_DATA : formatPercent(deliveryReliability)}</dd>
      </div>
      <div>
        <dt>CO2</dt>
        <dd>
          {co2KgPerKg === null
            ? NO_DATA
            : `${formatKg(co2KgPerKg)} kg CO2e per kg (product group average)`}
        </dd>
      </div>
      <div>
        <dt>Labels</dt>
        <dd>{labels.length === 0 ? 'None listed' : labels.map(formatLabel).join(', ')}</dd>
      </div>
    </dl>
  )
}
