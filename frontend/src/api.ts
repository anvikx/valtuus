// Single place that talks to the backend. Caddy (prod) and the Vite proxy (dev)
// route /api/* to FastAPI, so relative paths work in both.
const API_BASE = '/api'
const HEALTHY_STATUS = 'ok'

interface HealthResponse {
  readonly status: string
}

export type BackendHealth = 'ok' | 'down'

export async function getHealth(): Promise<BackendHealth> {
  const response = await fetch(`${API_BASE}/health`)

  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }

  const body = (await response.json()) as HealthResponse

  return body.status === HEALTHY_STATUS ? 'ok' : 'down'
}
