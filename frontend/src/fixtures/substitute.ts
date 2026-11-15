// c_demo with an equivalent: Valio Aimo cannot deliver the requested milk, so the cart holds the
// product its data names as the substitute (464306 lists 465039 in `substitutions`).
import type { WireCart, WireCartLine } from '../api.ts'
import { PENDING_CART } from './run1.ts'

const [MILK] = PENDING_CART.lines

const EQUIVALENT: WireCartLine = {
  ...MILK,
  offer_id: 'o_equivalent',
  product_id: '465039',
  name: 'Valio Eila® semi skimmed milk drink 1 l lactose free',
  unit_price: '1.05',
  line_total: '1050.00',
  decision: 'HUMAN',
  reason_codes: ['SUBSTITUTE_FOR_REQUESTED'],
  reason_sentences: [
    'Valio Eila® semi skimmed milk drink 1 l lactose free replaces the requested Valio Arki Eila 1 l.',
  ],
  substitute_for: {
    product_id: MILK.product_id,
    name: MILK.name,
    basis: 'VALIO_PAIR',
    reason_code: 'NOT_AVAILABLE',
    reason_sentence: 'Valio Aimo cannot deliver this product.',
    price_difference_per_unit: '0.04',
    per: 'L',
  },
}

export const SUBSTITUTE_EXTRAS: Partial<WireCart> = {
  reason_codes: ['OVER_AUTO_LIMIT', 'SUBSTITUTE_FOR_REQUESTED'],
  reason_sentences: ['1,050.00 EUR is over the 500.00 EUR limit.', ...EQUIVALENT.reason_sentences],
  current_reason_codes: ['OVER_AUTO_LIMIT', 'SUBSTITUTE_FOR_REQUESTED'],
  lines: [EQUIVALENT],
  total_ex_vat: '1050.00',
  delivery_day_total_ex_vat: '1050.00',
}
