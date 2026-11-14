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
//   c_conflict       waiting; approve and reject answer 409, and the cart is then EXPIRED
//   c_approve_fails  waiting; approve answers 503
//   c_unavailable    every read answers 503
import type { WireAuditRecord, WireCart, WireRequest, WireResponse } from '../api.ts'
import {
  ORDER_CONFIRMATION,
  PENDING_CART,
  agentOrderedCart,
  agentOrderedRecords,
  cartWithId,
  expiredCart,
  expiredRecords,
  orderedCart,
  orderedRecords,
  rejectedCart,
  rejectedRecords,
  waitingRecords,
} from './run1.ts'

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

const AUTH_PATH = /^\/v1\/auth\/(login|logout|me)$/
const CART_PATH = /^\/v1\/carts\/([^/]+)(?:\/(approve|reject))?$/
const AUDIT_PATH = /^\/v1\/audit\/([^/]+)$/

type Outcome = 'waiting' | 'ordered' | 'agentOrdered' | 'rejected' | 'expired'

interface CartRecord {
  readonly outcome: Outcome
  readonly rejectReason: string
}

// Fields the run 1 cart leaves empty. They stay on the cart after a decision.
const CART_EXTRAS: Readonly<Record<string, Partial<WireCart>>> = {
  [ANSWERS_ID]: {
    clarifications: ['Order it even if it is over the limit?', 'Yes, order it.'],
    delivery_day_total_ex_vat: '1415.00',
  },
}

const START_OUTCOME: Readonly<Record<string, Outcome>> = {
  c_demo: 'waiting',
  c_ordered: 'ordered',
  c_no_approval: 'agentOrdered',
  [ANSWERS_ID]: 'waiting',
  c_rejected: 'rejected',
  c_expired: 'expired',
  [CONFLICT_ID]: 'waiting',
  [APPROVE_FAILS_ID]: 'waiting',
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
  return {
    ...baseCart(cartId, cart),
    ...CART_EXTRAS[cartId],
  }
}

function baseCart(cartId: string, { outcome, rejectReason }: CartRecord): WireCart {
  if (outcome === 'ordered') {
    return orderedCart(cartId)
  }

  if (outcome === 'agentOrdered') {
    return agentOrderedCart(cartId)
  }

  if (outcome === 'rejected') {
    return rejectedCart(cartId, rejectReason)
  }

  if (outcome === 'expired') {
    return expiredCart(cartId)
  }

  return cartWithId(PENDING_CART, cartId)
}

function wireRecords(cartId: string, { outcome, rejectReason }: CartRecord): WireAuditRecord[] {
  if (outcome === 'ordered') {
    return orderedRecords(cartId)
  }

  if (outcome === 'agentOrdered') {
    return agentOrderedRecords(cartId)
  }

  if (outcome === 'rejected') {
    return rejectedRecords(cartId, rejectReason)
  }

  if (outcome === 'expired') {
    return expiredRecords(cartId)
  }

  return waitingRecords(cartId)
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

// A wrong state answers 409 and leaves the cart as it is, like the backend. c_conflict
// expires first, to act out a deadline that passes while the page is open.
function decide(cartId: string, cart: CartRecord, action: string, body: unknown): WireResponse {
  if (cartId === CONFLICT_ID) {
    saveCart(cartId, { ...cart, outcome: 'expired' })
    return reply(STATUS.conflict)
  }

  if (cart.outcome !== 'waiting') {
    return reply(STATUS.conflict)
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

  const rejected: CartRecord = { outcome: 'rejected', rejectReason: reason }
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

  return decide(cartId, cart, action, request.body)
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

function route(request: WireRequest): WireResponse {
  const authMatch = AUTH_PATH.exec(request.path)
  if (authMatch !== null) {
    return answerAuth(authMatch[1], request.body)
  }

  if (!isSignedIn()) {
    return reply(STATUS.unauthorized)
  }

  const cartMatch = CART_PATH.exec(request.path)
  if (cartMatch !== null) {
    return answerCart(request, decodeURIComponent(cartMatch[1]), cartMatch[2])
  }

  const auditMatch = AUDIT_PATH.exec(request.path)
  if (auditMatch !== null) {
    return answerAudit(decodeURIComponent(auditMatch[1]))
  }

  return reply(STATUS.notFound)
}

export async function answerFixture(request: WireRequest): Promise<WireResponse> {
  await new Promise((resolve) => {
    setTimeout(resolve, LATENCY_MS)
  })

  return route(request)
}
