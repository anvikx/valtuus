import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getOfferReview, type CartLine, type OfferTrust } from './api.ts'
import type { SigningKey } from './jws.ts'

async function getOfferTrust(lines: readonly CartLine[]): Promise<OfferTrust> {
  return (await getOfferReview(lines)).trust
}

// The backend signs offers with this issuer. A token from any other issuer proves nothing here.
const ISSUER = 'Valio Aimo (mock)'
const KEY_ID = 'test-key'
const JWKS_PATH = '/.well-known/jwks.json'
const OFFER_PATH = '/api/v1/offers/'

interface SignedLine {
  readonly product_id: string
  readonly unit_price: string
}

interface OfferPayload {
  readonly offer_id: string
  readonly issuer: string
  readonly source_time: string
  readonly lines: readonly SignedLine[]
}

function base64Url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/, '')
}

function encodeJson(value: unknown): string {
  return base64Url(new TextEncoder().encode(JSON.stringify(value)))
}

async function newKeys(): Promise<CryptoKeyPair> {
  return (await crypto.subtle.generateKey('Ed25519', true, ['sign', 'verify'])) as CryptoKeyPair
}

async function publicJwk(keys: CryptoKeyPair): Promise<SigningKey> {
  return { ...(await crypto.subtle.exportKey('jwk', keys.publicKey)), kid: KEY_ID }
}

async function sign(keys: CryptoKeyPair, payload: OfferPayload): Promise<string> {
  const signingInput = `${encodeJson({ alg: 'EdDSA', kid: KEY_ID })}.${encodeJson(payload)}`
  const signature = await crypto.subtle.sign(
    'Ed25519',
    keys.privateKey,
    new TextEncoder().encode(signingInput),
  )
  return `${signingInput}.${base64Url(new Uint8Array(signature))}`
}

function offer(offerId: string, sourceTime: string, unitPrice = '1.50'): OfferPayload {
  return {
    offer_id: offerId,
    issuer: ISSUER,
    source_time: sourceTime,
    lines: [{ product_id: `p_${offerId}`, unit_price: unitPrice }],
  }
}

function line(offerId: string, unitPrice = '1.50'): CartLine {
  return {
    offerId,
    productId: `p_${offerId}`,
    name: 'Valio Eila maitojuoma 1,5 l',
    qty: 1,
    unitPrice,
    lineTotal: unitPrice,
    deliveryDate: '2026-11-16',
    stock: { kind: 'in-stock' },
  }
}

// The fake backend: the JWKS, and each offer id to its stored signature (null when unsigned).
// Returns the offer ids in the order the page asked for them.
function serve(jwk: SigningKey, signatures: Readonly<Record<string, string | null>>): string[] {
  const asked: string[] = []
  vi.stubGlobal('fetch', async (url: string) => {
    if (url === JWKS_PATH) {
      return Response.json({ keys: [jwk] })
    }

    const offerId = decodeURIComponent(url.slice(OFFER_PATH.length))
    asked.push(offerId)
    return Response.json({ offer_id: offerId, signature: signatures[offerId] ?? null })
  })
  return asked
}

describe('getOfferTrust', () => {
  let keys: CryptoKeyPair
  let jwk: SigningKey

  beforeEach(async () => {
    keys = await newKeys()
    jwk = await publicJwk(keys)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // "Stock as of" must never claim fresher stock than the oldest answer behind one line.
  // The offsets differ, so a text sort would pick 08:30Z (10:30 local) as the oldest.
  it('verifies every offer and shows the oldest stock time', async () => {
    serve(jwk, {
      o_new: await sign(keys, offer('o_new', '2026-11-15T08:30:00Z')),
      o_old: await sign(keys, offer('o_old', '2026-11-15T09:00:00+02:00')),
    })

    const trust = await getOfferTrust([line('o_new'), line('o_old')])

    expect(trust).toEqual({ kind: 'verified', stockAsOf: '2026-11-15T09:00:00+02:00' })
  })

  // A cart often has many lines from one offer. One read per offer keeps the page light.
  it('reads each offer once', async () => {
    const twoLines = {
      ...offer('o_1', '2026-11-15T10:00:00+02:00'),
      lines: [
        { product_id: 'p_a', unit_price: '1.50' },
        { product_id: 'p_b', unit_price: '2.00' },
      ],
    }
    const asked = serve(jwk, { o_1: await sign(keys, twoLines) })
    const lines = [
      { ...line('o_1'), productId: 'p_a' },
      { ...line('o_1', '2.00'), productId: 'p_b' },
    ]

    const trust = await getOfferTrust(lines)

    expect(trust.kind).toBe('verified')
    expect(asked).toEqual(['o_1'])
  })

  // A token signed by a key the gateway does not publish proves nothing.
  it('refuses a signature from an unknown key', async () => {
    const stranger = await newKeys()
    serve(jwk, { o_1: await sign(stranger, offer('o_1', '2026-11-15T10:00:00+02:00')) })

    const trust = await getOfferTrust([line('o_1')])

    expect(trust.kind).toBe('invalid')
  })

  // Both prices come from one Decimal, so a trailing zero must not turn a true price false.
  it('accepts the same price written with another scale', async () => {
    serve(jwk, { o_1: await sign(keys, offer('o_1', '2026-11-15T10:00:00+02:00', '1.5')) })

    const trust = await getOfferTrust([line('o_1', '1.50')])

    expect(trust.kind).toBe('verified')
  })

  // "Price fixed" is about what the page shows. A valid signature on another price is a lie.
  it('refuses a line whose price is not the signed price', async () => {
    serve(jwk, { o_1: await sign(keys, offer('o_1', '2026-11-15T10:00:00+02:00')) })

    const trust = await getOfferTrust([line('o_1', '9.99')])

    expect(trust.kind).toBe('invalid')
  })

  // A changed byte in the token must break the mark, else the check proves nothing.
  it('refuses a tampered signature', async () => {
    const token = await sign(keys, offer('o_1', '2026-11-15T10:00:00+02:00'))
    const tampered = `${token.slice(0, -4)}${token.endsWith('AAAA') ? 'BBBB' : 'AAAA'}`
    serve(jwk, { o_1: tampered })

    const trust = await getOfferTrust([line('o_1')])

    expect(trust.kind).toBe('invalid')
  })

  // A key that signs anything for another issuer must not vouch for a Valio Aimo price.
  it('refuses a signature from another issuer', async () => {
    const foreign = { ...offer('o_1', '2026-11-15T10:00:00+02:00'), issuer: 'Someone else' }
    serve(jwk, { o_1: await sign(keys, foreign) })

    const trust = await getOfferTrust([line('o_1')])

    expect(trust.kind).toBe('invalid')
  })

  // Offers stored before signing went live have no signature. The page says so, not "invalid".
  it('says unsigned when one offer has no signature', async () => {
    serve(jwk, {
      o_signed: await sign(keys, offer('o_signed', '2026-11-15T10:00:00+02:00')),
      o_unsigned: null,
    })

    const trust = await getOfferTrust([line('o_signed'), line('o_unsigned')])

    expect(trust).toEqual({ kind: 'unsigned' })
  })

  // No lines means nothing was checked, so the caller must show "not checked", not "verified".
  it('says unchecked on a cart with no lines', async () => {
    serve(jwk, {})

    const trust = await getOfferTrust([])

    expect(trust).toEqual({ kind: 'unchecked' })
  })
})
