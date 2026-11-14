// Sign in round trip: a 401 sends the user to /login?next=<path>, and sign in sends them back.
import { ApiError } from './api.ts'

const LOGIN_PATH = '/login'
const NEXT_PARAM = 'next'
const HOME_PATH = '/'

export function isSignedOut(error: unknown): boolean {
  return error instanceof ApiError && error.kind === 'unauthenticated'
}

export function redirectToLogin(): void {
  const { pathname, search } = window.location
  const query = new URLSearchParams({ [NEXT_PARAM]: `${pathname}${search}` })
  window.location.assign(`${LOGIN_PATH}?${query.toString()}`)
}

// Only a path on this site. "//evil.example" or "/\evil.example" would leave it after sign in.
export function returnPath(): string {
  const next = new URLSearchParams(window.location.search).get(NEXT_PARAM)
  if (next === null || !next.startsWith('/')) {
    return HOME_PATH
  }

  const target = new URL(next, window.location.origin)
  if (target.origin !== window.location.origin || target.pathname === LOGIN_PATH) {
    return HOME_PATH
  }

  return `${target.pathname}${target.search}`
}
