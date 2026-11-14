import type { ReactElement } from 'react'

import type { AllergenPolicy, Mandate } from '../api.ts'
import { formatAllergen, formatAttribute } from '../format.ts'
import { money } from './ResultScreen.tsx'

const CURRENCY = 'EUR'

export const POLICY_WORDS: Readonly<Record<AllergenPolicy, string>> = {
  ask: 'Send the order to me',
  block: 'Do not order the product',
  order: 'Order the product',
}

const MUST_APPROVE = [
  'Larger orders',
  'Partial stock or stock that is not confirmed',
  'A brand that is not preferred',
  'A later delivery date than asked',
  'A repeated order',
  'A pack size that gives much more than the request',
]

const NEVER = [
  'Order a product that contains a forbidden allergen',
  'Order after the order deadline',
  'Change a price',
  'Approve its own cart',
  'Send a rejected cart again',
]

interface MandateViewProps {
  readonly mandate: Mandate
  readonly onEdit: () => void
}

interface RowProps {
  readonly term: string
  readonly children: string
  readonly isEmpty?: boolean
}

function Row({ term, children, isEmpty = false }: RowProps): ReactElement {
  return (
    <div className="mandate-row">
      <dt>{term}</dt>
      <dd className={isEmpty ? 'muted' : undefined}>{children}</dd>
    </div>
  )
}

function listOrNone(values: readonly string[]): string {
  return values.length === 0 ? 'None' : values.join(', ')
}

interface RuleListProps {
  readonly id: string
  readonly title: string
  readonly items: readonly string[]
}

function RuleList({ id, title, items }: RuleListProps): ReactElement {
  return (
    <section aria-labelledby={id} className="mandate-section">
      <h2 className="heading" id={id}>
        {title}
      </h2>
      <ul className="mandate-bullets">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

export function MandateView({ mandate, onEdit }: MandateViewProps): ReactElement {
  const required = mandate.required.map(formatAttribute)
  const forbidden = mandate.forbidden.map(formatAllergen)

  return (
    <div className="mandate-columns">
      <div className="mandate-column">
        <section aria-labelledby="mandate-alone" className="mandate-section">
          <h2 className="heading" id="mandate-alone">
            What the agent may order alone
          </h2>
          <p className="muted">Totals ex VAT.</p>
          <dl className="mandate-rows">
            <Row term="Per order">{money(mandate.maxOrder, CURRENCY)}</Row>
            <Row term="Per delivery day">{money(mandate.maxPerDay, CURRENCY)}</Row>
          </dl>
        </section>

        <section aria-labelledby="mandate-rules" className="mandate-section">
          <h2 className="heading" id="mandate-rules">
            Product rules
          </h2>
          <dl className="mandate-rows">
            <Row isEmpty={mandate.preferredBrands.length === 0} term="Preferred brands">
              {listOrNone(mandate.preferredBrands)}
            </Row>
            <Row isEmpty={required.length === 0} term="Every product must be">
              {listOrNone(required)}
            </Row>
            <Row isEmpty={forbidden.length === 0} term="Does not contain">
              {listOrNone(forbidden)}
            </Row>
            <Row term="Allergen data missing">{POLICY_WORDS[mandate.unknownPolicy]}</Row>
          </dl>
        </section>

        <button className="button button-outline mandate-edit" type="button" onClick={onEdit}>
          Edit
        </button>
      </div>

      <div className="mandate-column">
        <RuleList id="mandate-person" items={MUST_APPROVE} title="A person must approve" />
        <RuleList id="mandate-never" items={NEVER} title="The agent can never" />
      </div>
    </div>
  )
}
