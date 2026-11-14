// Sign in round trip: a 401 sends the user to /login?next=<path>, and sign in sends them back.
import { ApiError } from './api.ts'

const LOGIN_PATH = '/login'
const NEXT_PARAM = 'next'
// The main user's home is the inbox, so a sign in with no link lands there.
const HOME_PATH = '/inbox'

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

  // The origin check alone is not enough: "/.//evil.example" stays on this origin, but its
  // clean pathname is "//evil.example", which location.assign reads as another host.
  const target = new URL(next, window.location.origin)
  const isOtherHost = target.origin !== window.location.origin || target.pathname.startsWith('//')
  if (isOtherHost || target.pathname === LOGIN_PATH) {
    return HOME_PATH
  }

  return `${target.pathname}${target.search}`
}
