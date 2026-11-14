// Single place that talks to the backend. Caddy (prod) and the Vite proxy (dev)
// route /api/* to FastAPI, so relative paths work in both.
// Wire shapes (snake_case, status strings) stay in this file. The UI gets the domain types below.
import { verifyJws, type JwsPayload, type SigningKey } from './jws.ts'

const API_BASE = '/api'
// Agents look the key up at this fixed root path, so it is outside /api.
const JWKS_PATH = '/.well-known/jwks.json'
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
  put: 'PUT',
} as const

const AUTH_PATH = {
  login: '/auth/login',
  me: '/auth/me',
} as const

const WIRE_STATE_TO_STATUS: Readonly<Record<string, CartStatus>> = {
  PENDING_APPROVAL: 'waiting',
  ORDERED: 'ordered',
  REJECTED: 'rejected',
  EXPIRED: 'expired',
  DENIED: 'denied',
  // Not on the backend yet. The handoff lists it for a cart that the buyer cancels.
  WITHDRAWN: 'withdrawn',
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
const FIRST_REVISION = 1

const WIRE_UPDATER_TO_LABEL: Readonly<Record<string, string>> = {
  AGENT: 'the agent',
  MAIN_USER: 'you',
}

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
  readonly user_id: string
  readonly buyer_id: string | null
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

// The version the user last saw, kept while an update waits for Review.
export interface WireCartVersion {
  readonly lines: readonly WireCartLine[]
  readonly total_ex_vat: string
  readonly delivery_day_total_ex_vat: string
  readonly reason_sentences: readonly string[]
  readonly updated_at: string
  readonly updated_by: string
  readonly summary: string
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
  // Not on the backend yet, so both are optional. A missing revision reads as 1.
  readonly revision?: number
  readonly previous_version?: WireCartVersion | null
}

export interface WireOrderLine {
  readonly product_id: string
  readonly gtin: string | null
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

export interface WireMandate {
  readonly buyer_id: string
  readonly version: number
  readonly max_auto_order_value: string
  readonly max_auto_value_per_delivery_date: string
  readonly preferred_brands: readonly string[]
  readonly forbidden_allergens: readonly string[]
  readonly allergen_unknown_policy: string
}

export interface WireMandateResponse {
  readonly mandate: WireMandate
}

export interface WireMandateUpdate {
  readonly max_auto_order_value: string
  readonly max_auto_value_per_delivery_date: string
  readonly preferred_brands: readonly string[]
  readonly forbidden_allergens: readonly string[]
  readonly allergen_unknown_policy: string
}

interface HealthResponse {
  readonly status: string
}

// Domain types for the UI.

export type BackendHealth = 'ok' | 'down'

// 'closed' covers a state this page does not decide on (AUTO).
export type CartStatus =
  'waiting' | 'ordered' | 'rejected' | 'expired' | 'denied' | 'withdrawn' | 'closed'

export type FlowPhase = 'request' | 'lookup' | 'order' | 'approval'

// ask: the main user decides. block: the agent may not order the product.
export type AllergenPolicy = 'ask' | 'block' | 'order'

export type ApiErrorKind = 'unauthenticated' | 'conflict' | 'failed'

export interface Session {
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

export interface CartUpdate {
  readonly at: string
  readonly by: string
  // Plain words for what changed, for example "1,000 L to 800 L". The backend writes it.
  readonly summary: string
  readonly previousLines: readonly CartLine[]
  readonly previousTotal: string
  readonly previousDeliveryDayTotal: string
  // The reasons name the total, so the old ones stay with the old total until Review.
  readonly previousReasons: readonly string[]
}

// What the change sheet sends. A line with no entry is unchanged.
export interface CartChange {
  readonly quantities: Readonly<Record<string, number>>
  readonly removed: readonly string[]
  readonly note: string
}

export interface Cart {
  readonly id: string
  // Approve and reject send it, so a decision only applies to the version the user saw.
  readonly revision: number
  // Set while the cart differs from the version the user last saw.
  readonly update: CartUpdate | null
  readonly status: CartStatus
  readonly requestText: string
  readonly clarifications: readonly string[]
  readonly understood: UnderstoodRequest | null
  readonly reasons: readonly string[]
  readonly lines: readonly CartLine[]
  readonly total: string
  // Automatic orders for the same delivery day plus this cart.
  readonly deliveryDayTotal: string
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

// unchecked: the keys or the order could not be loaded, or the browser has no Ed25519.
export type OrderTrust =
  | { readonly kind: 'verified'; readonly issuer: string }
  | { readonly kind: 'unsigned' }
  | { readonly kind: 'invalid' }
  | { readonly kind: 'unchecked' }

export interface AuditEntry {
  readonly id: string
  readonly phase: FlowPhase
  readonly sentence: string
  readonly at: string
  // Who the gateway recorded. Null for the request line the UI builds from the cart.
  readonly actor: string | null
  // Pretty JSON of the call and the answer. Null when the record carries none.
  readonly input: string | null
  readonly output: string | null
}

export interface AuditTrail {
  readonly entries: readonly AuditEntry[]
  readonly agentName: string | null
  readonly startedAt: string | null
  readonly elapsedSeconds: number | null
}

export interface Mandate {
  readonly version: number
  // Money stays a string both ways. Never parse it to a number.
  readonly maxOrder: string
  readonly maxPerDay: string
  readonly preferredBrands: readonly string[]
  readonly forbidden: readonly string[]
  readonly unknownPolicy: AllergenPolicy
}

export type MandateEdit = Omit<Mandate, 'version'>

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

function toUpdate(wire: WireCartVersion | null | undefined): CartUpdate | null {
  if (wire === null || wire === undefined) {
    return null
  }

  return {
    at: wire.updated_at,
    by: WIRE_UPDATER_TO_LABEL[wire.updated_by] ?? 'the agent',
    summary: wire.summary,
    previousLines: wire.lines.map(toCartLine),
    previousTotal: wire.total_ex_vat,
    previousDeliveryDayTotal: wire.delivery_day_total_ex_vat,
    previousReasons: wire.reason_sentences,
  }
}

function toCart(wire: WireCart): Cart {
  return {
    id: wire.cart_id,
    revision: wire.revision ?? FIRST_REVISION,
    update: toUpdate(wire.previous_version),
    status: WIRE_STATE_TO_STATUS[wire.state] ?? 'closed',
    requestText: wire.request_text,
    clarifications: wire.clarifications,
    understood: toUnderstood(wire.interpreted_request),
    reasons: wire.reason_sentences,
    lines: wire.lines.map(toCartLine),
    total: wire.total_ex_vat,
    deliveryDayTotal: wire.delivery_day_total_ex_vat,
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

const JSON_INDENT = 2

function prettyJson(value: Readonly<Record<string, unknown>>): string | null {
  return Object.keys(value).length === 0 ? null : JSON.stringify(value, null, JSON_INDENT)
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
        actor: record.actor,
        input: prettyJson(record.input),
        output: prettyJson(record.output),
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

const WIRE_POLICY_TO_POLICY: Readonly<Record<string, AllergenPolicy>> = {
  HUMAN: 'ask',
  DENY: 'block',
  AUTO: 'order',
}

const POLICY_TO_WIRE_POLICY: Readonly<Record<AllergenPolicy, string>> = {
  ask: 'HUMAN',
  block: 'DENY',
  order: 'AUTO',
}

function toMandate({ mandate }: WireMandateResponse): Mandate {
  return {
    version: mandate.version,
    maxOrder: mandate.max_auto_order_value,
    maxPerDay: mandate.max_auto_value_per_delivery_date,
    preferredBrands: mandate.preferred_brands,
    forbidden: mandate.forbidden_allergens,
    // An unknown value must not read as permission to order.
    unknownPolicy: WIRE_POLICY_TO_POLICY[mandate.allergen_unknown_policy] ?? 'ask',
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

// A user with no buyer (staff) has no carts to approve here, so the page treats it as signed
// out and shows the login page.
export async function getSession(): Promise<Session> {
  const wire = (await call(HTTP_METHOD.get, AUTH_PATH.me)) as WireSession
  if (wire.buyer_id === null) {
    throw new ApiError('unauthenticated')
  }

  return {
    buyerId: wire.buyer_id,
  }
}

// One main user, so the backend asks only for the password. A wrong one throws ApiError
// 'unauthenticated'.
export async function signIn(password: string): Promise<void> {
  await call(HTTP_METHOD.post, AUTH_PATH.login, { password })
}

export async function getCart(cartId: string): Promise<Cart> {
  return toCart((await call(HTTP_METHOD.get, cartPath(cartId))) as WireCart)
}

// The backend orders the list: carts that wait first (earliest deadline on top), then the rest.
export async function listCarts(): Promise<readonly Cart[]> {
  const wire = (await call(HTTP_METHOD.get, '/carts')) as readonly WireCart[]
  return wire.map(toCart)
}

export async function getAudit(cartId: string): Promise<AuditTrail> {
  const path = `/audit/${encodeURIComponent(cartId)}`
  return toAuditTrail((await call(HTTP_METHOD.get, path)) as WireAudit)
}

export async function approveCart(cartId: string, revision: number): Promise<OrderConfirmation> {
  const wire = await call(HTTP_METHOD.post, `${cartPath(cartId)}/approve`, { revision })
  return toConfirmation(wire as WireOrderConfirmation)
}

// The fixture backend never gets here: its orders are unsigned.
async function getSigningKeys(): Promise<readonly SigningKey[]> {
  const response = await fetch(JWKS_PATH)
  if (!response.ok) {
    throw new Error(`Signing keys failed: ${response.status}`)
  }

  const body = (await response.json()) as { readonly keys: readonly SigningKey[] }
  return body.keys
}

// The page shows the cart, so the signed statement must be about that cart: a valid signature
// on another order proves nothing here.
function isSignedCart(payload: JwsPayload, orderId: string, cart: Cart): boolean {
  return (
    payload.order_id === orderId &&
    payload.cart_id === cart.id &&
    payload.total_ex_vat === cart.total &&
    typeof payload.issuer === 'string'
  )
}

// Throws when the check cannot run. The issuer comes from the signed payload, not the body.
export async function getOrderTrust(orderId: string, cart: Cart): Promise<OrderTrust> {
  const path = `/orders/${encodeURIComponent(orderId)}`
  const order = (await call(HTTP_METHOD.get, path)) as WireOrderConfirmation
  if (order.signature === null) {
    return { kind: 'unsigned' }
  }

  const payload = await verifyJws(order.signature, await getSigningKeys())
  if (payload === null || !isSignedCart(payload, orderId, cart)) {
    return { kind: 'invalid' }
  }

  return { kind: 'verified', issuer: String(payload.issuer) }
}

export async function rejectCart(cartId: string, revision: number, reason: string): Promise<Cart> {
  const wire = await call(HTTP_METHOD.post, `${cartPath(cartId)}/reject`, { revision, reason })
  return toCart(wire as WireCart)
}

// Backend gap: this route does not exist yet. The answer is the cart as a new revision.
export async function changeCart(
  cartId: string,
  revision: number,
  { quantities, removed, note }: CartChange,
): Promise<Cart> {
  const wire = await call(HTTP_METHOD.post, `${cartPath(cartId)}/changes`, {
    revision,
    quantities,
    removed_product_ids: removed,
    note,
  })
  return toCart(wire as WireCart)
}

export async function getMandate(): Promise<Mandate> {
  return toMandate((await call(HTTP_METHOD.get, '/mandate')) as WireMandateResponse)
}

// Saving makes a new version. The answer carries it.
export async function saveMandate(edit: MandateEdit): Promise<Mandate> {
  const update: WireMandateUpdate = {
    max_auto_order_value: edit.maxOrder,
    max_auto_value_per_delivery_date: edit.maxPerDay,
    preferred_brands: edit.preferredBrands,
    forbidden_allergens: edit.forbidden,
    allergen_unknown_policy: POLICY_TO_WIRE_POLICY[edit.unknownPolicy],
  }
  return toMandate((await call(HTTP_METHOD.put, '/mandate', update)) as WireMandateResponse)
}
