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
// The prototype's only signer. Another issuer in a valid signature is not this gateway's.
const MOCK_ISSUER = 'Valio Aimo (mock)'

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

const AGENTS_PATH = '/agents'
const AGENT_ACTIVE = 'ACTIVE'

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
  // The agent withdrew the cart because the buyer no longer wants it.
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

export interface WireSubstituteFor {
  readonly product_id: string
  readonly name: string
  readonly basis: string
  readonly reason_code: string
  readonly reason_sentence: string
  readonly price_difference_per_unit: string
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
  readonly substitute_for: WireSubstituteFor | null
  readonly stock_model: string | null
  readonly available_qty: number | null
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
  // Optional so a fixture can leave them out. A missing revision reads as 1.
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

// Decimals come as numbers or strings, so the facts are read through Number().
interface WireOfferLine {
  readonly product_id: string
  readonly delivery_reliability: number | string | null
  readonly co2_kg_per_kg: number | string | null
  readonly labels: readonly string[]
}

// Only the fields the trust check and the line facts read. The rest of the offer is in the
// signed payload.
interface WireSignedOffer {
  readonly signature: string | null
  readonly lines?: readonly WireOfferLine[]
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
  readonly required_attributes: readonly string[]
  readonly forbidden_allergens: readonly string[]
  readonly allergen_unknown_policy: string
  readonly can_auto_order: boolean
}

export interface WireMandateResponse {
  readonly mandate: WireMandate
}

// One key. A new key for the same agent keeps the agent_id, so one agent can have more.
export interface WireAgent {
  readonly agent_id: string
  readonly agent_name: string
  readonly status: string
  readonly last_used_at: string | null
}

export interface WireMandateUpdate {
  readonly max_auto_order_value: string
  readonly max_auto_value_per_delivery_date: string
  readonly preferred_brands: readonly string[]
  readonly required_attributes: readonly string[]
  readonly forbidden_allergens: readonly string[]
  readonly allergen_unknown_policy: string
  readonly can_auto_order: boolean
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

// Rule 10 words for a line. A null count is never "unlimited". 'short': fewer than qty, which a
// DENIED cart can show.
export type LineStock =
  | { readonly kind: 'in-stock' }
  | { readonly kind: 'unconfirmed' }
  | { readonly kind: 'short'; readonly available: number }

// The requested product a line replaces, because Valio Aimo cannot supply it.
export interface Substitution {
  readonly requestedName: string
  // Why the requested product is not in the cart. It says "this product" for the requested one.
  readonly reason: string
  // Substitute price minus requested price per sales unit, ex VAT. Negative when cheaper.
  readonly priceDifference: string
}

export interface CartLine {
  // The signed offer that holds the line's price.
  readonly offerId: string
  readonly productId: string
  readonly name: string
  readonly qty: number
  readonly unitPrice: string
  readonly lineTotal: string
  readonly deliveryDate: string
  readonly stock: LineStock
  readonly substituteFor: Substitution | null
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
  // The rules changed while the cart waited, and the agent could now order it alone.
  readonly isInsideLimits: boolean
}

export interface OrderConfirmation {
  readonly orderId: string
  readonly total: string
  readonly currency: string
  readonly approvedBy: string | null
  readonly placedAt: string
}

// unchecked: the keys or the signed object could not be loaded, or the browser has no Ed25519.
type NotVerified =
  { readonly kind: 'unsigned' } | { readonly kind: 'invalid' } | { readonly kind: 'unchecked' }

export type OrderTrust = { readonly kind: 'verified' } | NotVerified

// stockAsOf: the oldest stock answer behind the cart's lines.
export type OfferTrust = { readonly kind: 'verified'; readonly stockAsOf: string } | NotVerified

// Product facts from the signed offer line. null is "no data", never 0.
export interface OfferFacts {
  // 0 to 1.
  readonly deliveryReliability: number | null
  // A product group average, not a measure of this product.
  readonly co2KgPerKg: number | null
  readonly labels: readonly string[]
}

export type OfferFactsByLine = ReadonlyMap<string, OfferFacts>

export interface OfferReview {
  readonly trust: OfferTrust
  // A line is missing here when its offer could not be read.
  readonly facts: OfferFactsByLine
}

export function offerFactsKey({ offerId, productId }: CartLine): string {
  return `${offerId}/${productId}`
}

export interface AuditEntry {
  readonly id: string
  readonly phase: FlowPhase
  // The gateway step (SEARCH, OFFER, ...). Null for the request line the UI builds from the cart.
  readonly step: string | null
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
  readonly required: readonly string[]
  readonly forbidden: readonly string[]
  readonly unknownPolicy: AllergenPolicy
  readonly canAutoOrder: boolean
}

export type MandateEdit = Omit<Mandate, 'version'>

export interface Agent {
  readonly id: string
  readonly name: string
  // True while any key of the agent works.
  readonly isActive: boolean
  // Null: the agent never called.
  readonly lastUsedAt: string | null
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

const WIRE_STOCK_MODEL = 'STOCK'
const WIRE_STOCK_UNCONFIRMED = 'STOCK_UNCONFIRMED'

// A STOCK line with a null count is either "in stock" or the unconfirmed marker. The backend
// keeps that difference only as the line's STOCK_UNCONFIRMED reason.
function toLineStock({ stock_model, reason_codes, available_qty, qty }: WireCartLine): LineStock {
  if (stock_model !== WIRE_STOCK_MODEL || reason_codes.includes(WIRE_STOCK_UNCONFIRMED)) {
    return { kind: 'unconfirmed' }
  }

  if (available_qty !== null && available_qty < qty) {
    return { kind: 'short', available: available_qty }
  }

  return { kind: 'in-stock' }
}

function toSubstitution(wire: WireSubstituteFor | null): Substitution | null {
  if (wire === null) {
    return null
  }

  return {
    requestedName: wire.name,
    reason: wire.reason_sentence,
    priceDifference: wire.price_difference_per_unit,
  }
}

function toCartLine(wire: WireCartLine): CartLine {
  return {
    offerId: wire.offer_id,
    productId: wire.product_id,
    name: wire.name,
    qty: wire.qty,
    unitPrice: wire.unit_price,
    lineTotal: wire.line_total,
    deliveryDate: wire.delivery_date,
    stock: toLineStock(wire),
    substituteFor: toSubstitution(wire.substitute_for),
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

const WIRE_AUTO_DECISION = 'AUTO'

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
    isInsideLimits: wire.current_decision === WIRE_AUTO_DECISION,
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
        step: record.step,
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
    required: mandate.required_attributes,
    forbidden: mandate.forbidden_allergens,
    // An unknown value must not read as permission to order.
    unknownPolicy: WIRE_POLICY_TO_POLICY[mandate.allergen_unknown_policy] ?? 'ask',
    // A missing value must not read as permission to order alone.
    canAutoOrder: mandate.can_auto_order === true,
  }
}

function laterTime(first: string | null, second: string | null): string | null {
  if (first === null || second === null) {
    return first ?? second
  }

  // Parse: the offsets can differ, so the strings do not sort by time.
  return Date.parse(second) > Date.parse(first) ? second : first
}

// One row per agent, not per key, so a replaced key does not show as a second agent.
function toAgents(keys: readonly WireAgent[]): Agent[] {
  const byId = new Map<string, Agent>()
  for (const key of keys) {
    const seen = byId.get(key.agent_id)
    byId.set(key.agent_id, {
      id: key.agent_id,
      name: key.agent_name,
      isActive: (seen?.isActive ?? false) || key.status === AGENT_ACTIVE,
      lastUsedAt: laterTime(seen?.lastUsedAt ?? null, key.last_used_at),
    })
  }

  return [...byId.values()]
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
    payload.issuer === MOCK_ISSUER
  )
}

// Throws when the check cannot run.
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

  return { kind: 'verified' }
}

// product_id to unit_price of the signed offer lines. Anything else in the payload is ignored.
function signedPrices(payload: JwsPayload): ReadonlyMap<unknown, unknown> {
  const lines: unknown[] = Array.isArray(payload.lines) ? payload.lines : []
  return new Map(
    lines
      .filter((line): line is Readonly<Record<string, unknown>> => {
        return typeof line === 'object' && line !== null
      })
      .map((line) => [line.product_id, line.unit_price]),
  )
}

// "Price fixed" must hold for what the page shows: each line of this offer has the signed price.
// Number() so "1.5" and "1.50" match. Both come from the same Decimal.
function isSignedOffer(payload: JwsPayload, offerId: string, lines: readonly CartLine[]): boolean {
  if (payload.offer_id !== offerId || payload.issuer !== MOCK_ISSUER) {
    return false
  }

  if (typeof payload.source_time !== 'string') {
    return false
  }

  const prices = signedPrices(payload)
  return lines
    .filter((line) => line.offerId === offerId)
    .every((line) => Number(prices.get(line.productId)) === Number(line.unitPrice))
}

interface ReadOffer {
  readonly offerId: string
  readonly wire: WireSignedOffer
}

interface SignedOffer {
  readonly offerId: string
  readonly signature: string
}

async function readOffer(offerId: string): Promise<WireSignedOffer> {
  const path = `/offers/${encodeURIComponent(offerId)}`
  return (await call(HTTP_METHOD.get, path)) as WireSignedOffer
}

function toNumber(value: number | string | null): number | null {
  return value === null ? null : Number(value)
}

function factsOf(offers: readonly ReadOffer[]): OfferFactsByLine {
  return new Map(
    offers.flatMap(({ offerId, wire }) =>
      (wire.lines ?? []).map((line): [string, OfferFacts] => [
        `${offerId}/${line.product_id}`,
        {
          deliveryReliability: toNumber(line.delivery_reliability),
          co2KgPerKg: toNumber(line.co2_kg_per_kg),
          labels: line.labels,
        },
      ]),
    ),
  )
}

// The offer's stock time when its signature is valid and covers the lines, else null.
async function signedStockTime(
  { offerId, signature }: SignedOffer,
  keys: readonly SigningKey[],
  lines: readonly CartLine[],
): Promise<string | null> {
  const payload = await verifyJws(signature, keys)
  if (payload === null || !isSignedOffer(payload, offerId, lines)) {
    return null
  }

  return String(payload.source_time)
}

// Throws when the check cannot run, for example on a cart with no lines.
// The stock time comes from the signed payload, not the body.
async function checkOffers(
  offers: readonly ReadOffer[],
  lines: readonly CartLine[],
): Promise<OfferTrust> {
  const signed = offers.flatMap(({ offerId, wire }) =>
    wire.signature === null ? [] : [{ offerId, signature: wire.signature }],
  )
  if (signed.length < offers.length) {
    return { kind: 'unsigned' }
  }

  const keys = await getSigningKeys()
  const stockTimes = await Promise.all(signed.map((offer) => signedStockTime(offer, keys, lines)))
  const validTimes = stockTimes.filter((time) => time !== null)
  if (validTimes.length < stockTimes.length) {
    return { kind: 'invalid' }
  }

  // The oldest stock answer, so the page never claims fresher stock than one line has.
  const oldest = validTimes.toSorted((a, b) => Date.parse(a) - Date.parse(b))[0]
  if (oldest === undefined) {
    throw new Error('A cart with no lines has no offer to check.')
  }

  return { kind: 'verified', stockAsOf: oldest }
}

// Reads each stored offer once for both the trust check and the line facts. A failed read
// hides only its own part: no facts for that offer, and an unchecked trust mark.
export async function getOfferReview(lines: readonly CartLine[]): Promise<OfferReview> {
  const offerIds = [...new Set(lines.map((line) => line.offerId))]
  const results = await Promise.allSettled(offerIds.map(readOffer))
  const read = results.flatMap((result, index): ReadOffer[] =>
    result.status === 'fulfilled' ? [{ offerId: offerIds[index], wire: result.value }] : [],
  )
  const facts = factsOf(read)
  if (read.length < offerIds.length) {
    return { trust: { kind: 'unchecked' }, facts }
  }

  const trust = await checkOffers(read, lines).catch((): OfferTrust => ({ kind: 'unchecked' }))
  return { trust, facts }
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

export async function listAgents(): Promise<readonly Agent[]> {
  return toAgents((await call(HTTP_METHOD.get, AGENTS_PATH)) as WireAgent[])
}

// Revokes every key of the agent. The answer is the new agent list.
export async function stopAgent(agentId: string): Promise<readonly Agent[]> {
  const path = `${AGENTS_PATH}/${encodeURIComponent(agentId)}/revoke`
  return toAgents((await call(HTTP_METHOD.post, path)) as WireAgent[])
}

// Saving makes a new version. The answer carries it.
export async function saveMandate(edit: MandateEdit): Promise<Mandate> {
  const update: WireMandateUpdate = {
    max_auto_order_value: edit.maxOrder,
    max_auto_value_per_delivery_date: edit.maxPerDay,
    preferred_brands: edit.preferredBrands,
    required_attributes: edit.required,
    forbidden_allergens: edit.forbidden,
    allergen_unknown_policy: POLICY_TO_WIRE_POLICY[edit.unknownPolicy],
    can_auto_order: edit.canAutoOrder,
  }
  return toMandate((await call(HTTP_METHOD.put, '/mandate', update)) as WireMandateResponse)
}
