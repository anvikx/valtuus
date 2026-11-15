// Run 1 of the demo: 1,000 L lactose free milk, over the 500.00 EUR auto limit.
// Shapes and values follow the backend's create_cart, OrderConfirmation and AuditRecord bodies.
import type { WireAuditRecord, WireCart, WireOrderConfirmation } from '../api.ts'

const MAIN_USER = 'main user of hotel-1'
const AGENT = 'claude-code (agent)'
const GATEWAY = 'gateway'
const DECIDED_AT = '2026-11-14T10:04:12+02:00'
const EXPIRED_AT = '2026-11-15T17:00:02+02:00'
const DENIED_SENTENCE =
  'Valio Arki Eila 1 l contains milk protein, which this buyer does not allow.'

export const PENDING_CART: WireCart = {
  cart_id: 'c_demo',
  state: 'PENDING_APPROVAL',
  decision: 'HUMAN',
  reason_codes: ['OVER_AUTO_LIMIT'],
  reason_sentences: ['1,010.00 EUR is over the 500.00 EUR limit.'],
  current_decision: 'HUMAN',
  current_reason_codes: ['OVER_AUTO_LIMIT'],
  request_text: 'I need 1,000 litres of lactose-free milk by Monday.',
  clarifications: [],
  interpreted_request: {
    query: 'lactose free milk',
    required_attributes: ['FREE_FROM_LACTOSE'],
    quantity: 1000,
    unit: 'L',
    deliver_by: '2026-11-16',
    preferred_brands: [],
  },
  lines: [
    {
      offer_id: 'o_demo',
      product_id: '464306',
      name: 'Valio Arki Eila 1 l',
      qty: 1000,
      unit_price: '1.01',
      line_total: '1010.00',
      delivery_date: '2026-11-16',
      closing_time: '2026-11-15T17:00:00',
      decision: 'AUTO',
      reason_codes: [],
      reason_sentences: [],
      substitute_for: null,
    },
  ],
  total_ex_vat: '1010.00',
  currency: 'EUR',
  mandate_version: 1,
  valid_until: '2026-11-14T10:16:00+02:00',
  approve_before: '2026-11-15T17:00:00',
  duplicate_of_order_id: null,
  delivery_day_total_ex_vat: '1010.00',
  order_id: null,
  previous_reject_reason: null,
  decided_by: null,
  decided_at: null,
  reject_reason: null,
  approve_url: 'https://junction.anvik.fi/carts/c_demo',
  revision: 1,
  previous_version: null,
}

// A cart line from a Valio pair substitute: the requested milk could not be delivered.
export const SUBSTITUTE_EXTRAS: Partial<WireCart> = {
  reason_codes: ['SUBSTITUTE_FOR_REQUESTED'],
  reason_sentences: [
    '12 x Arla Whole milk drink 1 L UHT lactose free replaces the requested ' +
      'Valio whole milk 1 l lactose free UHT.',
  ],
  current_reason_codes: ['SUBSTITUTE_FOR_REQUESTED'],
  lines: [
    {
      offer_id: 'o_demo',
      product_id: '464768',
      name: '12 x Arla Whole milk drink 1 L UHT lactose free',
      qty: 1000,
      unit_price: '1.21',
      line_total: '1210.00',
      delivery_date: '2026-11-16',
      closing_time: '2026-11-15T17:00:00',
      decision: 'HUMAN',
      reason_codes: ['SUBSTITUTE_FOR_REQUESTED'],
      reason_sentences: [],
      substitute_for: {
        product_id: '464073',
        name: 'Valio whole milk 1 l lactose free UHT',
        basis: 'VALIO_PAIR',
        reason_code: 'NOT_AVAILABLE',
        reason_sentence: 'Valio Aimo cannot deliver this product.',
        price_difference_per_unit: '0.20',
        per: 'L',
      },
    },
  ],
  total_ex_vat: '1210.00',
  delivery_day_total_ex_vat: '1210.00',
}

export const ORDER_CONFIRMATION: WireOrderConfirmation = {
  order_id: 'ord_demo',
  cart_id: 'c_demo',
  buyer_id: 'hotel-1',
  status: 'CONFIRMED',
  ledger: 'PROTOTYPE',
  lines: [
    {
      product_id: '464306',
      gtin: 'gtin_demo',
      name: 'Valio Arki Eila 1 l',
      qty: 1000,
      unit_price: '1.01',
      line_total: '1010.00',
      delivery_date: '2026-11-16',
      substitute_for: null,
    },
  ],
  total_ex_vat: '1010.00',
  currency: 'EUR',
  placed_at: DECIDED_AT,
  placed_by: AGENT,
  approved_by: MAIN_USER,
  offer_ids: ['o_demo'],
  mandate_version: 1,
  issuer: 'Valio Aimo (mock)',
  signature: null,
}

export function cartWithId(cart: WireCart, cartId: string): WireCart {
  return {
    ...cart,
    cart_id: cartId,
    approve_url: `https://junction.anvik.fi/carts/${cartId}`,
  }
}

export function orderedCart(cartId: string): WireCart {
  return {
    ...cartWithId(PENDING_CART, cartId),
    state: 'ORDERED',
    order_id: ORDER_CONFIRMATION.order_id,
    decided_by: MAIN_USER,
    decided_at: DECIDED_AT,
  }
}

// The limit raise: the agent's second checkout placed the order with no approver.
export function agentOrderedCart(cartId: string): WireCart {
  return {
    ...orderedCart(cartId),
    decided_by: null,
    decided_at: null,
  }
}

export function rejectedCart(cartId: string, reason: string): WireCart {
  return {
    ...cartWithId(PENDING_CART, cartId),
    state: 'REJECTED',
    decided_by: MAIN_USER,
    decided_at: DECIDED_AT,
    reject_reason: reason,
  }
}

export function expiredCart(cartId: string): WireCart {
  return {
    ...cartWithId(PENDING_CART, cartId),
    state: 'EXPIRED',
    reason_codes: ['CUTOFF_PASSED'],
    reason_sentences: ['The order deadline was Sun 15 Nov 17:00.'],
  }
}

// Approve runs the policy again. A rule now forbids the order, so the cart closes as DENIED.
export function deniedCart(cartId: string): WireCart {
  return {
    ...cartWithId(PENDING_CART, cartId),
    state: 'DENIED',
    current_decision: 'DENY',
    reason_codes: ['FORBIDDEN_ALLERGEN'],
    current_reason_codes: ['FORBIDDEN_ALLERGEN'],
    reason_sentences: [DENIED_SENTENCE],
  }
}

export function withdrawnCart(cartId: string): WireCart {
  return {
    ...cartWithId(PENDING_CART, cartId),
    state: 'WITHDRAWN',
  }
}

// cartId is null for SEARCH and OFFER: they happen before a cart exists.
function record(
  cartId: string | null,
  id: string,
  fields: Pick<WireAuditRecord, 'step' | 'phase' | 'actor' | 'sentence' | 'created_at'> &
    Partial<Pick<WireAuditRecord, 'input' | 'output'>>,
): WireAuditRecord {
  return {
    record_id: `a_${id}`,
    cart_id: cartId,
    request_id: 'r_demo',
    input: {},
    output: {},
    decision: null,
    reason_codes: [],
    mandate_version: null,
    ...fields,
  }
}

// SEARCH, OFFER, CART and POLICY: the records every run 1 cart has while it waits.
export function waitingRecords(cartId: string): WireAuditRecord[] {
  return [
    record(null, 'search', {
      step: 'SEARCH',
      phase: 'LOOKUP',
      actor: AGENT,
      sentence: 'The agent searched for lactose free milk. 6 products matched.',
      input: { query: 'lactose free milk' },
      output: { matched: 6 },
      created_at: '2026-11-14T10:00:05+02:00',
    }),
    record(null, 'offer', {
      step: 'OFFER',
      phase: 'LOOKUP',
      actor: AGENT,
      sentence: 'The gateway gave 3 signed offers and rejected 3 products: order deadline passed.',
      input: { product_ids: ['464306', '464398', '469363'], quantity: 1000, unit: 'L' },
      output: { offers: 3, rejected: 3, reason_codes: ['CUTOFF_PASSED'] },
      created_at: '2026-11-14T10:00:41+02:00',
    }),
    record(cartId, 'cart', {
      step: 'CART',
      phase: 'ORDER',
      actor: AGENT,
      sentence:
        'The agent built a cart with 464306: lowest price, full quantity in stock. 1,010.00 EUR ex VAT, fixed price.',
      created_at: '2026-11-14T10:01:30+02:00',
    }),
    {
      ...record(cartId, 'policy', {
        step: 'POLICY',
        phase: 'APPROVAL',
        actor: GATEWAY,
        sentence:
          'The policy sent the cart to a person: 1,010.00 EUR is over the 500.00 EUR limit.',
        created_at: '2026-11-14T10:01:31+02:00',
      }),
      decision: 'HUMAN',
      reason_codes: ['OVER_AUTO_LIMIT'],
      mandate_version: 1,
    },
  ]
}

export function orderedRecords(cartId: string): WireAuditRecord[] {
  return [
    ...waitingRecords(cartId),
    record(cartId, 'approval', {
      step: 'APPROVAL',
      phase: 'APPROVAL',
      actor: MAIN_USER,
      sentence: 'The main user approved.',
      created_at: DECIDED_AT,
    }),
    record(cartId, 'order', {
      step: 'ORDER',
      phase: 'APPROVAL',
      actor: MAIN_USER,
      sentence: 'The order was committed at the signed price.',
      created_at: DECIDED_AT,
    }),
  ]
}

// After the limit raise, POLICY runs again under mandate version 2 and gives AUTO.
export function agentOrderedRecords(cartId: string): WireAuditRecord[] {
  return [
    ...waitingRecords(cartId),
    {
      ...record(cartId, 'policy_v2', {
        step: 'POLICY',
        phase: 'APPROVAL',
        actor: GATEWAY,
        sentence:
          'The limit is now 1,500.00 EUR (mandate version 2), so the agent may place this order.',
        created_at: DECIDED_AT,
      }),
      decision: 'AUTO',
      mandate_version: 2,
    },
    record(cartId, 'order', {
      step: 'ORDER',
      phase: 'APPROVAL',
      actor: AGENT,
      sentence: 'The order was committed at the signed price.',
      created_at: DECIDED_AT,
    }),
  ]
}

export function rejectedRecords(cartId: string, reason: string): WireAuditRecord[] {
  return [
    ...waitingRecords(cartId),
    record(cartId, 'approval', {
      step: 'APPROVAL',
      phase: 'APPROVAL',
      actor: MAIN_USER,
      sentence: `The main user rejected the cart: "${reason}".`,
      created_at: DECIDED_AT,
    }),
  ]
}

export function expiredRecords(cartId: string): WireAuditRecord[] {
  return [
    ...waitingRecords(cartId),
    record(cartId, 'expiry', {
      step: 'APPROVAL',
      phase: 'APPROVAL',
      actor: GATEWAY,
      sentence:
        'Nobody decided before the order deadline. The order deadline was Sun 15 Nov 17:00.',
      created_at: EXPIRED_AT,
    }),
  ]
}

export function deniedRecords(cartId: string): WireAuditRecord[] {
  return [
    ...waitingRecords(cartId),
    {
      ...record(cartId, 'policy_deny', {
        step: 'POLICY',
        phase: 'APPROVAL',
        actor: GATEWAY,
        sentence: `The policy denied the order. ${DENIED_SENTENCE}`,
        created_at: DECIDED_AT,
      }),
      decision: 'DENY',
      reason_codes: ['FORBIDDEN_ALLERGEN'],
      mandate_version: 2,
    },
  ]
}
