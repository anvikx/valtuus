// Single place that talks to the backend. Caddy (prod) and the Vite proxy (dev)
// route /api/* to FastAPI, so relative paths work in both.
// Wire shapes (snake_case, status strings) stay in this file. The UI gets the domain types below.
const API_BASE = '/api'
const API_V1 = '/v1'
const HEALTHY_STATUS = 'ok'
const JSON_HEADERS = { 'Content-Type': 'application/json' }
const IS_FIXTURE_MODE = import.meta.env.VITE_USE_FIXTURES === 'true'

const HTTP_STATUS = {
  okFirst: 200,
  okLast: 299,
  unauthorized: 401,
  conflict: 409,
} as const

const HTTP_METHOD = {
  get: 'GET',
  post: 'POST',
} as const

const WIRE_STATE_TO_STATUS: Readonly<Record<string, CartStatus>> = {
  PENDING_APPROVAL: 'waiting',
  ORDERED: 'ordered',
  REJECTED: 'rejected',
  EXPIRED: 'expired',
}

const WIRE_PHASE_TO_PHASE: Readonly<Record<string, FlowPhase>> = {
  REQUEST: 'request',
  LOOKUP: 'lookup',
  ORDER: 'order',
  APPROVAL: 'approval',
}

const UNIT_LABEL: Readonly<Record<string, string>> = {
  L: 'L',
  KG: 'kg',
  PCS: 'pcs',
}

const WIRE_STEP = {
  search: 'SEARCH',
  cart: 'CART',
  order: 'ORDER',
} as const

const MS_PER_SECOND = 1000

// Wire types: the backend's JSON, field by field. Fixtures use them too.

export interface WireRequest {
  readonly method: string
  readonly path: string
  readonly body: unknown
}

export interface WireResponse {
  readonly status: number
  readonly body: unknown
}

export interface WireSession {
  readonly username: string
  readonly buyer_id: string
  readonly role: string
}

export interface WireInterpretedRequest {
  readonly query: string
  readonly required_attributes: readonly string[]
  readonly quantity: number | null
  readonly unit: string | null
  readonly deliver_by: string | null
  readonly preferred_brands: readonly string[]
}

export interface WireCartLine {
  readonly offer_id: string
  readonly product_id: string
  readonly name: string
  readonly qty: number
  readonly unit_price: string
  readonly line_total: string
  readonly delivery_date: string
  readonly closing_time: string
  readonly decision: string
  readonly reason_codes: readonly string[]
  readonly reason_sentences: readonly string[]
  readonly substitute_for: unknown
}

export interface WireCart {
  readonly cart_id: string
  readonly state: string
  readonly decision: string
  readonly reason_codes: readonly string[]
  readonly reason_sentences: readonly string[]
  readonly current_decision: string
  readonly current_reason_codes: readonly string[]
  readonly request_text: string
  readonly clarifications: readonly string[]
  readonly interpreted_request: WireInterpretedRequest | null
  readonly lines: readonly WireCartLine[]
  readonly total_ex_vat: string
  readonly currency: string
  readonly mandate_version: number
  readonly valid_until: string
  readonly approve_before: string
  readonly duplicate_of_order_id: string | null
  readonly delivery_day_total_ex_vat: string
  readonly order_id: string | null
  readonly previous_reject_reason: string | null
  readonly decided_by: string | null
  readonly decided_at: string | null
  readonly reject_reason: string | null
  readonly approve_url: string | null
}

export interface WireOrderLine {
  readonly product_id: string
  readonly gtin: string
  readonly name: string
  readonly qty: number
  readonly unit_price: string
  readonly line_total: string
  readonly delivery_date: string
  readonly substitute_for: unknown
}

export interface WireOrderConfirmation {
  readonly order_id: string
  readonly cart_id: string
  readonly buyer_id: string
  readonly status: string
  readonly ledger: string
  readonly lines: readonly WireOrderLine[]
  readonly total_ex_vat: string
  readonly currency: string
  readonly placed_at: string
  readonly placed_by: string
  readonly approved_by: string | null
  readonly offer_ids: readonly string[]
  readonly mandate_version: number
  readonly issuer: string
  readonly signature: string | null
}

export interface WireAuditRecord {
  readonly record_id: string
  readonly cart_id: string | null
  readonly request_id: string | null
  readonly step: string
  readonly phase: string | null
  readonly actor: string
  readonly input: Readonly<Record<string, unknown>>
  readonly output: Readonly<Record<string, unknown>>
  readonly decision: string | null
  readonly reason_codes: readonly string[]
  readonly mandate_version: number | null
  readonly sentence: string
  readonly created_at: string
}

export interface WireAudit {
  readonly cart_id: string
  readonly records: readonly WireAuditRecord[]
}

interface HealthResponse {
  readonly status: string
}

// Domain types for the UI.

export type BackendHealth = 'ok' | 'down'

// 'closed' covers the states this page does not decide on (AUTO, DENIED).
export type CartStatus = 'waiting' | 'ordered' | 'rejected' | 'expired' | 'closed'

export type FlowPhase = 'request' | 'lookup' | 'order' | 'approval'

export type ApiErrorKind = 'unauthenticated' | 'conflict' | 'failed'

export interface Session {
  readonly username: string
  readonly buyerId: string
}

export interface UnderstoodRequest {
  readonly quantity: number | null
  readonly unit: string | null
  readonly attributes: readonly string[]
  readonly deliverBy: string | null
}

export interface CartLine {
  readonly productId: string
  readonly name: string
  readonly qty: number
  readonly unitPrice: string
  readonly lineTotal: string
  readonly deliveryDate: string
}

export interface Cart {
  readonly id: string
  readonly status: CartStatus
  readonly requestText: string
  readonly understood: UnderstoodRequest | null
  readonly reasons: readonly string[]
  readonly lines: readonly CartLine[]
  readonly total: string
  readonly currency: string
  readonly approveBefore: string
  readonly orderId: string | null
  readonly decidedBy: string | null
  readonly decidedAt: string | null
  readonly rejectReason: string | null
}

export interface OrderConfirmation {
  readonly orderId: string
  readonly total: string
  readonly currency: string
  readonly approvedBy: string | null
  readonly placedAt: string
}

export interface AuditEntry {
  readonly id: string
  readonly phase: FlowPhase
  readonly sentence: string
  readonly at: string
}

export interface AuditTrail {
  readonly entries: readonly AuditEntry[]
  readonly agentName: string | null
  readonly startedAt: string | null
  readonly elapsedSeconds: number | null
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind

  constructor(kind: ApiErrorKind) {
    super(kind)
    this.kind = kind
  }
}

// Transport: the real backend, or the fixture server when VITE_USE_FIXTURES=true.

function parseJson(text: string): unknown {
  if (text === '') {
    return null
  }

  try {
    return JSON.parse(text)
  } catch {
    // A proxy error page is HTML, not JSON. The status code still says what happened.
    return null
  }
}

async function sendToBackend({ method, path, body }: WireRequest): Promise<WireResponse> {
  const hasBody = body !== undefined
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: 'include',
    headers: hasBody ? JSON_HEADERS : undefined,
    body: hasBody ? JSON.stringify(body) : undefined,
  })

  return {
    status: response.status,
    body: parseJson(await response.text()),
  }
}

async function send(request: WireRequest): Promise<WireResponse> {
  if (!IS_FIXTURE_MODE) {
    return sendToBackend(request)
  }

  const { answerFixture } = await import('./fixtures/server.ts')
  return answerFixture(request)
}

function errorKindFor(status: number): ApiErrorKind {
  if (status === HTTP_STATUS.unauthorized) {
    return 'unauthenticated'
  }

  if (status === HTTP_STATUS.conflict) {
    return 'conflict'
  }

  return 'failed'
}

async function call(method: string, path: string, body?: unknown): Promise<unknown> {
  let response: WireResponse
  try {
    response = await send({
      method,
      path: `${API_V1}${path}`,
      body,
    })
  } catch {
    throw new ApiError('failed')
  }

  const isOk = response.status >= HTTP_STATUS.okFirst && response.status <= HTTP_STATUS.okLast
  if (!isOk) {
    throw new ApiError(errorKindFor(response.status))
  }

  return response.body
}

// Wire to domain.

function toUnderstood(wire: WireInterpretedRequest | null): UnderstoodRequest | null {
  if (wire === null) {
    return null
  }

  return {
    quantity: wire.quantity,
    unit: wire.unit === null ? null : (UNIT_LABEL[wire.unit] ?? wire.unit),
    attributes: wire.required_attributes,
    deliverBy: wire.deliver_by,
  }
}

function toCartLine(wire: WireCartLine): CartLine {
  return {
    productId: wire.product_id,
    name: wire.name,
    qty: wire.qty,
    unitPrice: wire.unit_price,
    lineTotal: wire.line_total,
    deliveryDate: wire.delivery_date,
  }
}

function toCart(wire: WireCart): Cart {
  return {
    id: wire.cart_id,
    status: WIRE_STATE_TO_STATUS[wire.state] ?? 'closed',
    requestText: wire.request_text,
    understood: toUnderstood(wire.interpreted_request),
    reasons: wire.reason_sentences,
    lines: wire.lines.map(toCartLine),
    total: wire.total_ex_vat,
    currency: wire.currency,
    approveBefore: wire.approve_before,
    orderId: wire.order_id,
    decidedBy: wire.decided_by,
    decidedAt: wire.decided_at,
    rejectReason: wire.reject_reason,
  }
}

function toConfirmation(wire: WireOrderConfirmation): OrderConfirmation {
  return {
    orderId: wire.order_id,
    total: wire.total_ex_vat,
    currency: wire.currency,
    approvedBy: wire.approved_by,
    placedAt: wire.placed_at,
  }
}

function toAuditEntries(records: readonly WireAuditRecord[]): AuditEntry[] {
  return records.flatMap((record) => {
    const phase = record.phase === null ? undefined : WIRE_PHASE_TO_PHASE[record.phase]
    if (phase === undefined) {
      return []
    }

    return [
      {
        id: record.record_id,
        phase,
        sentence: record.sentence,
        at: record.created_at,
      },
    ]
  })
}

// Elapsed time = the ORDER record minus the first SEARCH record. A cart with no order
// (rejected, expired) runs to its last record.
function elapsedSeconds(records: readonly WireAuditRecord[]): number | null {
  const first = records.find((record) => record.step === WIRE_STEP.search) ?? records[0]
  const last = records.find((record) => record.step === WIRE_STEP.order) ?? records.at(-1)
  if (first === undefined || last === undefined) {
    return null
  }

  const elapsedMs = Date.parse(last.created_at) - Date.parse(first.created_at)
  return Number.isNaN(elapsedMs) ? null : Math.round(elapsedMs / MS_PER_SECOND)
}

function toAuditTrail(wire: WireAudit): AuditTrail {
  const cartRecord = wire.records.find((record) => record.step === WIRE_STEP.cart)

  return {
    entries: toAuditEntries(wire.records),
    agentName: cartRecord?.actor ?? null,
    startedAt: wire.records[0]?.created_at ?? null,
    elapsedSeconds: elapsedSeconds(wire.records),
  }
}

function cartPath(cartId: string): string {
  return `/carts/${encodeURIComponent(cartId)}`
}

// Operations.

export async function getHealth(): Promise<BackendHealth> {
  const response = await fetch(`${API_BASE}/health`, { credentials: 'include' })

  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }

  const body = (await response.json()) as HealthResponse

  return body.status === HEALTHY_STATUS ? 'ok' : 'down'
}

export async function getSession(): Promise<Session> {
  const wire = (await call(HTTP_METHOD.get, '/session')) as WireSession

  return {
    username: wire.username,
    buyerId: wire.buyer_id,
  }
}

// A wrong username or password throws ApiError 'unauthenticated'.
export async function signIn(username: string, password: string): Promise<void> {
  await call(HTTP_METHOD.post, '/session', {
    username,
    password,
  })
}

export async function getCart(cartId: string): Promise<Cart> {
  return toCart((await call(HTTP_METHOD.get, cartPath(cartId))) as WireCart)
}

export async function getAudit(cartId: string): Promise<AuditTrail> {
  const path = `/audit/${encodeURIComponent(cartId)}`
  return toAuditTrail((await call(HTTP_METHOD.get, path)) as WireAudit)
}

export async function approveCart(cartId: string): Promise<OrderConfirmation> {
  const wire = await call(HTTP_METHOD.post, `${cartPath(cartId)}/approve`, {})
  return toConfirmation(wire as WireOrderConfirmation)
}

export async function rejectCart(cartId: string, reason: string): Promise<Cart> {
  const wire = await call(HTTP_METHOD.post, `${cartPath(cartId)}/reject`, { reason })
  return toCart(wire as WireCart)
}
