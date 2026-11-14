// Checks a compact JWS with EdDSA (RFC 7515, RFC 8037) in the browser's Web Crypto.
const JWS_ALGORITHM = 'EdDSA'
const WEB_CRYPTO_ALGORITHM = 'Ed25519'
const JWS_PART_COUNT = 3

export interface SigningKey extends JsonWebKey {
  readonly kid?: string
}

export type JwsPayload = Readonly<Record<string, unknown>>

// atob accepts base64 without padding, so only the URL safe letters need a swap.
function decodeBase64Url(segment: string): Uint8Array<ArrayBuffer> | null {
  try {
    const binary = atob(segment.replaceAll('-', '+').replaceAll('_', '/'))
    return Uint8Array.from(binary, (char) => char.charCodeAt(0))
  } catch {
    return null
  }
}

function decodeJson(segment: string): unknown {
  const bytes = decodeBase64Url(segment)
  if (bytes === null) {
    return null
  }

  try {
    return JSON.parse(new TextDecoder().decode(bytes)) as unknown
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is JwsPayload {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// The payload when one of the keys checks the signature, else null. Throws when the browser
// has no Ed25519, so the caller can tell "not checked" from "invalid".
export async function verifyJws(
  token: string,
  keys: readonly SigningKey[],
): Promise<JwsPayload | null> {
  const parts = token.split('.')
  if (parts.length !== JWS_PART_COUNT) {
    return null
  }

  const [header, payload, signature] = parts as [string, string, string]
  const parsedHeader = decodeJson(header)
  const parsedPayload = decodeJson(payload)
  const signatureBytes = decodeBase64Url(signature)
  if (
    !isRecord(parsedHeader) ||
    parsedHeader.alg !== JWS_ALGORITHM ||
    !isRecord(parsedPayload) ||
    signatureBytes === null
  ) {
    return null
  }

  const jwk = keys.find((key) => key.kid === parsedHeader.kid)
  if (jwk === undefined) {
    return null
  }

  const key = await crypto.subtle.importKey('jwk', jwk, WEB_CRYPTO_ALGORITHM, false, ['verify'])
  const signingInput = new TextEncoder().encode(`${header}.${payload}`)
  const isValid = await crypto.subtle.verify(
    WEB_CRYPTO_ALGORITHM,
    key,
    signatureBytes,
    signingInput,
  )
  return isValid ? parsedPayload : null
}
