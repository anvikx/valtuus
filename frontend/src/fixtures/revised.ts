// Revision 2 of c_demo, and the change a save or an agent update makes to a cart.
// Money maths lives here, in the fixture, because the UI never adds money. The real backend
// sends every total as a string.
import type { WireCart, WireCartLine } from '../api.ts'
import { PENDING_CART } from './run1.ts'

const CENTS_PER_UNIT = 100
const AGENT_UPDATER = 'AGENT'
const UPDATED_AT = '2026-11-14T13:10:00+02:00'

const [MILK] = PENDING_CART.lines
export const MILK_ID = MILK.product_id

const MILK_800: WireCartLine = {
  ...MILK,
  qty: 800,
  line_total: '808.00',
}

const COFFEE: WireCartLine = {
  ...MILK,
  offer_id: 'o_coffee',
  product_id: '400100',
  name: 'Paulig Presidentti 500 g',
  qty: 10,
  unit_price: '5.50',
  line_total: '55.00',
}

export interface LineChange {
  readonly quantities?: Readonly<Record<string, number>>
  readonly removed_product_ids?: readonly string[]
}

export const REVISED_EXTRAS: Partial<WireCart> = {
  revision: 2,
  reason_sentences: ['863.00 EUR is over the 500.00 EUR limit.'],
  lines: [MILK_800, COFFEE],
  total_ex_vat: '863.00',
  delivery_day_total_ex_vat: '863.00',
  previous_version: {
    lines: PENDING_CART.lines,
    total_ex_vat: PENDING_CART.total_ex_vat,
    delivery_day_total_ex_vat: PENDING_CART.delivery_day_total_ex_vat,
    reason_sentences: PENDING_CART.reason_sentences,
    updated_at: UPDATED_AT,
    updated_by: AGENT_UPDATER,
    summary: '1,000 L to 800 L, and coffee added',
  },
}

function toCents(money: string): number {
  return Math.round(Number.parseFloat(money) * CENTS_PER_UNIT)
}

function toMoney(cents: number): string {
  return (cents / CENTS_PER_UNIT).toFixed(2)
}

function withQuantity(line: WireCartLine, qty: number): WireCartLine {
  return {
    ...line,
    qty,
    line_total: toMoney(toCents(line.unit_price) * qty),
  }
}

function describe(current: readonly WireCartLine[], change: LineChange): string {
  const quantities = change.quantities ?? {}
  const removed = change.removed_product_ids ?? []

  return current
    .flatMap((line) => {
      if (removed.includes(line.product_id)) {
        return [`${line.name} removed`]
      }

      const qty = quantities[line.product_id]
      return qty === undefined || qty === line.qty ? [] : [`${line.name} ${line.qty} to ${qty}`]
    })
    .join(', ')
}

// The next revision of a cart. The old lines and total go to previous_version, as the backend
// will keep them until the user taps Review.
export function reviseCart(current: WireCart, change: LineChange, updatedBy: string): WireCart {
  const quantities = change.quantities ?? {}
  const removed = change.removed_product_ids ?? []
  const lines = current.lines
    .filter((line) => !removed.includes(line.product_id))
    .map((line) => {
      const qty = quantities[line.product_id]
      return qty === undefined ? line : withQuantity(line, qty)
    })
  const total = toMoney(lines.reduce((sum, line) => sum + toCents(line.line_total), 0))

  return {
    ...current,
    revision: (current.revision ?? 1) + 1,
    lines,
    total_ex_vat: total,
    delivery_day_total_ex_vat: total,
    reason_sentences: [`${total} EUR is over the 500.00 EUR limit.`],
    previous_version: {
      lines: current.lines,
      total_ex_vat: current.total_ex_vat,
      delivery_day_total_ex_vat: current.delivery_day_total_ex_vat,
      reason_sentences: current.reason_sentences,
      updated_at: new Date().toISOString(),
      updated_by: updatedBy,
      summary: describe(current.lines, change),
    },
  }
}
