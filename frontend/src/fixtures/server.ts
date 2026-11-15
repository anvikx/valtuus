// Fixture backend for VITE_USE_FIXTURES=true. It answers the same routes and status codes as
// FastAPI, so api.ts runs its normal wire parsing on it. Sign in with the password demo.
//
// Cart ids:
//   c_demo           waiting; approve gives ORDERED, reject gives REJECTED
//   c_ordered        ORDERED
//   c_no_approval    ORDERED by the agent's checkout, no approver (the limit raise)
//   c_answers        waiting, with the buyer's answers and other automatic orders that day
//   c_rejected       REJECTED
//   c_expired        EXPIRED
//   c_denied         DENIED: a rule forbids the order
//   c_withdrawn      WITHDRAWN: the buyer cancelled it
//   c_conflict       waiting; approve and reject answer 409, and the cart is then EXPIRED
//   c_approve_fails  waiting; approve answers 503
//   c_unavailable    every read answers 503
//   c_revised        waiting, revision 2: the agent changed the milk and added coffee
//   c_revised_stale  like c_revised, but approve and reject answer 409 and a revision 3 shows
//
// Permissions: /permissions. /permissions?save=fail makes a save answer 503.
// Inbox: /inbox lists the carts above. /inbox?inbox=empty hides the waiting ones.
import type { WireAuditRecord, WireCart, WireMandate, WireRequest, WireResponse } from '../api.ts'
import {
  ORDER_CONFIRMATION,
  PENDING_CART,
  agentOrderedCart,
  agentOrderedRecords,
  cartWithId,
  deniedCart,
  deniedRecords,
  expiredCart,
  expiredRecords,
  orderedCart,
  orderedRecords,
  rejectedCart,
  rejectedRecords,
  waitingRecords,
  withdrawnCart,
} from './run1.ts'
import { MILK_ID, REVISED_EXTRAS, reviseCart, type LineChange } from './revised.ts'

const STATUS = {
  ok: 200,
  noContent: 204,
  unauthorized: 401,
  notFound: 404,
  conflict: 409,
  unprocessable: 422,
  unavailable: 503,
} as const

const FIXTURE_USER_ID = 'main'
const FIXTURE_PASSWORD = 'demo'
const SESSION_KEY = 'valtuus.fixture.session'
const STORE_KEY = 'valtuus.fixture.carts'
// Slow enough to see the disabled buttons and to test a double tap.
const LATENCY_MS = 600
const DEFAULT_REJECT_REASON = 'Too expensive'

const CONFLICT_ID = 'c_conflict'
const APPROVE_FAILS_ID = 'c_approve_fails'
const UNAVAILABLE_ID = 'c_unavailable'
const ANSWERS_ID = 'c_answers'
const REVISED_ID = 'c_revised'
const STALE_ID = 'c_revised_stale'
const AGENT_UPDATER = 'AGENT'
const USER_UPDATER = 'MAIN_USER'
const STALE_MILK_QTY = 700

const AUTH_PATH = /^\/v1\/auth\/(login|logout|me)$/
const CARTS_PATH = '/v1/carts'
const WAITING_STATE = 'PENDING_APPROVAL'
const EMPTY_INBOX_PARAM = 'inbox'
const EMPTY_INBOX_VALUE = 'empty'
const CART_PATH = /^\/v1\/carts\/([^/]+)(?:\/(approve|reject|changes))?$/
const MANDATE_PATH = '/v1/mandate'
const SAVE_FAILS_PARAM = 'save'
const SAVE_FAILS_VALUE = 'fail'
const AUDIT_PATH = /^\/v1\/audit\/([^/]+)$/
const ORDER_PATH = /^\/v1\/orders\/([^/]+)$/

type Outcome =
  'waiting' | 'ordered' | 'agentOrdered' | 'rejected' | 'expired' | 'denied' | 'withdrawn'

interface CartRecord {
  readonly outcome: Outcome
  readonly rejectReason: string
  // The cart after a change. It replaces the lines and total of the start cart.
  readonly revised?: WireCart
}

// Fields the run 1 cart leaves empty. They stay on the cart after a decision.
const CART_EXTRAS: Readonly<Record<string, Partial<WireCart>>> = {
  [ANSWERS_ID]: {
    clarifications: ['Order it even if it is over the limit?', 'Yes, order it.'],
    delivery_day_total_ex_vat: '1415.00',
  },
  [REVISED_ID]: REVISED_EXTRAS,
  [STALE_ID]: REVISED_EXTRAS,
}

const START_OUTCOME: Readonly<Record<string, Outcome>> = {
  c_demo: 'waiting',
  c_ordered: 'ordered',
  c_no_approval: 'agentOrdered',
  [ANSWERS_ID]: 'waiting',
  c_rejected: 'rejected',
  c_expired: 'expired',
  c_denied: 'denied',
  c_withdrawn: 'withdrawn',
  [CONFLICT_ID]: 'waiting',
  [APPROVE_FAILS_ID]: 'waiting',
  [REVISED_ID]: 'waiting',
  [STALE_ID]: 'waiting',
}

// Storage helpers. sessionStorage keeps a decision over a reload. It can throw in a private
// window, and then the fixtures run from memory.

const memory = new Map<string, string>()

function readItem(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return memory.get(key) ?? null
  }
}

function writeItem(key: string, value: string | null): void {
  try {
    if (value === null) {
      sessionStorage.removeItem(key)
    } else {
      sessionStorage.setItem(key, value)
    }
  } catch {
    if (value === null) {
      memory.delete(key)
    } else {
      memory.set(key, value)
    }
  }
}

function readCarts(): Record<string, CartRecord> {
  const text = readItem(STORE_KEY)
  return text === null ? {} : (JSON.parse(text) as Record<string, CartRecord>)
}

function findCart(cartId: string): CartRecord | null {
  const stored = readCarts()[cartId]
  if (stored !== undefined) {
    return stored
  }

  const outcome = START_OUTCOME[cartId]
  return outcome === undefined ? null : { outcome, rejectReason: DEFAULT_REJECT_REASON }
}

function saveCart(cartId: string, cart: CartRecord): void {
  writeItem(STORE_KEY, JSON.stringify({ ...readCarts(), [cartId]: cart }))
}

// Responses.

function reply(status: number, body: unknown = null): WireResponse {
  return {
    status,
    body,
  }
}

function wireCart(cartId: string, cart: CartRecord): WireCart {
  const { revised } = cart
  const base = {
    ...baseCart(cartId, cart),
    ...CART_EXTRAS[cartId],
  }
  if (revised === undefined) {
    return base
  }

  return {
    ...base,
    revision: revised.revision,
    lines: revised.lines,
    total_ex_vat: revised.total_ex_vat,
    delivery_day_total_ex_vat: revised.delivery_day_total_ex_vat,
    reason_sentences:
      base.state === WAITING_STATE ? revised.reason_sentences : base.reason_sentences,
    previous_version: revised.previous_version,
  }
}

// Maps, not if chains, so a new Outcome does not compile until it has a cart and records.
const CART_FOR: Readonly<Record<Outcome, (cartId: string, rejectReason: string) => WireCart>> = {
  waiting: (cartId) => cartWithId(PENDING_CART, cartId),
  ordered: orderedCart,
  agentOrdered: agentOrderedCart,
  rejected: rejectedCart,
  expired: expiredCart,
  denied: deniedCart,
  withdrawn: withdrawnCart,
}

// The backend has no record for a withdrawal yet, so a withdrawn cart shows the waiting ones.
const RECORDS_FOR: Readonly<
  Record<Outcome, (cartId: string, rejectReason: string) => WireAuditRecord[]>
> = {
  waiting: waitingRecords,
  ordered: orderedRecords,
  agentOrdered: agentOrderedRecords,
  rejected: rejectedRecords,
  expired: expiredRecords,
  denied: deniedRecords,
  withdrawn: waitingRecords,
}

function baseCart(cartId: string, { outcome, rejectReason }: CartRecord): WireCart {
  return CART_FOR[outcome](cartId, rejectReason)
}

function wireRecords(cartId: string, { outcome, rejectReason }: CartRecord): WireAuditRecord[] {
  return RECORDS_FOR[outcome](cartId, rejectReason)
}

function isSignedIn(): boolean {
  return readItem(SESSION_KEY) !== null
}

function answerAuth(action: string, body: unknown): WireResponse {
  if (action === 'login') {
    const { password } = body as { password: string }
    if (password !== FIXTURE_PASSWORD) {
      return reply(STATUS.unauthorized)
    }

    writeItem(SESSION_KEY, FIXTURE_USER_ID)
    return reply(STATUS.noContent)
  }

  if (action === 'logout') {
    writeItem(SESSION_KEY, null)
    return reply(STATUS.noContent)
  }

  if (!isSignedIn()) {
    return reply(STATUS.unauthorized)
  }

  return reply(STATUS.ok, {
    user_id: readItem(SESSION_KEY),
    buyer_id: 'hotel-1',
    role: 'MAIN_USER',
  })
}

// The decision names the revision the user saw. A different one means the cart changed since.
function isStaleRevision(cartId: string, cart: CartRecord, body: unknown): boolean {
  const { revision } = body as { revision?: number }
  return revision !== wireCart(cartId, cart).revision
}

// The agent sends a newer revision while the user reads the old one: the decision is refused,
// and the reload shows the update bar again.
function answerStale(cartId: string, cart: CartRecord): WireResponse {
  const revised = reviseCart(
    wireCart(cartId, cart),
    { quantities: { [MILK_ID]: STALE_MILK_QTY } },
    AGENT_UPDATER,
  )
  saveCart(cartId, { ...cart, revised })
  return reply(STATUS.conflict)
}

// A note alone changes no line, so the cart stays at its revision: the agent answers later.
function change(cartId: string, cart: CartRecord, body: unknown): WireResponse {
  const current = wireCart(cartId, cart)
  if (cart.outcome !== 'waiting' || isStaleRevision(cartId, cart, body)) {
    return reply(STATUS.conflict)
  }

  const lineChange = body as LineChange
  const isLineChanged =
    Object.keys(lineChange.quantities ?? {}).length > 0 ||
    (lineChange.removed_product_ids ?? []).length > 0
  if (!isLineChanged) {
    return reply(STATUS.ok, current)
  }

  const revised = reviseCart(current, lineChange, USER_UPDATER)
  saveCart(cartId, { ...cart, revised })
  return reply(STATUS.ok, revised)
}

// A wrong state answers 409 and leaves the cart as it is, like the backend. c_conflict
// expires first, to act out a deadline that passes while the page is open.
function decide(cartId: string, cart: CartRecord, action: string, body: unknown): WireResponse {
  if (cartId === CONFLICT_ID) {
    saveCart(cartId, { ...cart, outcome: 'expired' })
    return reply(STATUS.conflict)
  }

  if (cart.outcome !== 'waiting' || isStaleRevision(cartId, cart, body)) {
    return reply(STATUS.conflict)
  }

  if (cartId === STALE_ID && cart.revised === undefined) {
    return answerStale(cartId, cart)
  }

  if (action === 'approve') {
    if (cartId === APPROVE_FAILS_ID) {
      return reply(STATUS.unavailable)
    }

    saveCart(cartId, { ...cart, outcome: 'ordered' })
    return reply(STATUS.ok, {
      ...ORDER_CONFIRMATION,
      cart_id: cartId,
    })
  }

  const reason = (body as { reason?: string }).reason?.trim() ?? ''
  if (reason === '') {
    return reply(STATUS.unprocessable)
  }

  const rejected: CartRecord = {
    outcome: 'rejected',
    rejectReason: reason,
    revised: cart.revised,
  }
  saveCart(cartId, rejected)
  return reply(STATUS.ok, wireCart(cartId, rejected))
}

function answerCart(
  request: WireRequest,
  cartId: string,
  action: string | undefined,
): WireResponse {
  if (cartId === UNAVAILABLE_ID) {
    return reply(STATUS.unavailable)
  }

  const cart = findCart(cartId)
  if (cart === null) {
    return reply(STATUS.notFound)
  }

  if (action === undefined) {
    return reply(STATUS.ok, wireCart(cartId, cart))
  }

  if (action === 'changes') {
    return change(cartId, cart, request.body)
  }

  return decide(cartId, cart, action, request.body)
}

// The fixture decisions carry a fixed date. Moving them to now keeps "Decided today" filled
// whatever day the demo runs.
function answerList(): WireResponse {
  const isEmpty =
    new URLSearchParams(window.location.search).get(EMPTY_INBOX_PARAM) === EMPTY_INBOX_VALUE
  const now = new Date().toISOString()
  const carts = Object.keys(START_OUTCOME).flatMap((cartId) => {
    const wire = wireCart(cartId, findCart(cartId) as CartRecord)
    if (wire.state === WAITING_STATE) {
      return isEmpty ? [] : [wire]
    }

    return [wire.decided_at === null ? wire : { ...wire, decided_at: now }]
  })

  return reply(STATUS.ok, [
    ...carts.filter((cart) => cart.state === WAITING_STATE),
    ...carts.filter((cart) => cart.state !== WAITING_STATE),
  ])
}

function answerAudit(cartId: string): WireResponse {
  const cart = findCart(cartId)
  if (cart === null) {
    return reply(STATUS.notFound)
  }

  return reply(STATUS.ok, {
    cart_id: cartId,
    records: wireRecords(cartId, cart),
  })
}

// In memory, so a reload resets the mandate to version 1. /permissions?save=fail makes
// every save answer 503.
let mandate: WireMandate = {
  buyer_id: 'hotel-1',
  version: 1,
  max_auto_order_value: '500.00',
  max_auto_value_per_delivery_date: '500.00',
  preferred_brands: [],
  required_attributes: [],
  forbidden_allergens: [],
  allergen_unknown_policy: 'HUMAN',
  can_auto_order: false,
}

function answerMandate(request: WireRequest): WireResponse {
  if (request.method === 'GET') {
    return reply(STATUS.ok, { mandate })
  }

  const params = new URLSearchParams(window.location.search)
  if (params.get(SAVE_FAILS_PARAM) === SAVE_FAILS_VALUE) {
    return reply(STATUS.unavailable)
  }

  mandate = {
    ...mandate,
    ...(request.body as Partial<WireMandate>),
    version: mandate.version + 1,
  }
  return reply(STATUS.ok, { mandate })
}

function route(request: WireRequest): WireResponse {
  const authMatch = AUTH_PATH.exec(request.path)
  if (authMatch !== null) {
    return answerAuth(authMatch[1], request.body)
  }

  if (!isSignedIn()) {
    return reply(STATUS.unauthorized)
  }

  if (request.path === CARTS_PATH) {
    return answerList()
  }

  const cartMatch = CART_PATH.exec(request.path)
  if (cartMatch !== null) {
    return answerCart(request, decodeURIComponent(cartMatch[1]), cartMatch[2])
  }

  if (request.path === MANDATE_PATH) {
    return answerMandate(request)
  }

  const auditMatch = AUDIT_PATH.exec(request.path)
  if (auditMatch !== null) {
    return answerAudit(decodeURIComponent(auditMatch[1]))
  }

  // Fixture orders are unsigned, so the page shows the development mark.
  const orderMatch = ORDER_PATH.exec(request.path)
  if (orderMatch !== null) {
    return reply(STATUS.ok, {
      ...ORDER_CONFIRMATION,
      order_id: decodeURIComponent(orderMatch[1]),
    })
  }

  return reply(STATUS.notFound)
}

export async function answerFixture(request: WireRequest): Promise<WireResponse> {
  await new Promise((resolve) => {
    setTimeout(resolve, LATENCY_MS)
  })

  return route(request)
}
