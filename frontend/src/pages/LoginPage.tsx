import { useState, type ReactElement, type SubmitEvent } from 'react'

import { signIn } from '../api.ts'
import { isSignedOut, returnPath } from '../session.ts'

type LoginState = 'idle' | 'sending' | 'wrongLogin' | 'failed'

const CART_PATH_PREFIX = '/carts/'

// One sentence for both fields: never tell which of the two is wrong.
const ERROR_TEXT: Readonly<Partial<Record<LoginState, string>>> = {
  wrongLogin: 'That username or password is not correct.',
  failed: 'Sign in did not work. Try again.',
}

// Main user login. It shows no order data: the cart loads only after sign in.
export function LoginPage(): ReactElement {
  const [state, setState] = useState<LoginState>('idle')
  const [isPasswordShown, setIsPasswordShown] = useState(false)
  const nextPath = returnPath()
  const isSending = state === 'sending'
  const errorText = ERROR_TEXT[state]

  async function submit(event: SubmitEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault()
    if (isSending) {
      return
    }

    const form = new FormData(event.currentTarget)
    setState('sending')
    try {
      await signIn(String(form.get('username')), String(form.get('password')))
    } catch (error: unknown) {
      setState(isSignedOut(error) ? 'wrongLogin' : 'failed')
      return
    }

    window.location.assign(nextPath)
  }

  return (
    <main className="stack">
      <h1 className="page-title">Sign in</h1>
      <p>
        {nextPath.startsWith(CART_PATH_PREFIX)
          ? 'An order waits for your approval. Sign in to see it.'
          : 'Sign in to Valtuus.'}
      </p>

      <form className="stack" onSubmit={(event) => void submit(event)}>
        <div className="field">
          <label className="field-label" htmlFor="username">
            Username
          </label>
          <input className="input" id="username" name="username" autoComplete="username" required />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="password">
            Password
          </label>
          <div className="input-row">
            <input
              className="input"
              id="password"
              name="password"
              type={isPasswordShown ? 'text' : 'password'}
              autoComplete="current-password"
              required
            />
            <button
              className="button-quiet"
              type="button"
              aria-pressed={isPasswordShown}
              aria-controls="password"
              onClick={() => {
                setIsPasswordShown(!isPasswordShown)
              }}
            >
              {isPasswordShown ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>

        {errorText === undefined ? null : (
          <p className="alert" role="alert">
            {errorText}
          </p>
        )}

        <button className="button button-primary" type="submit" disabled={isSending}>
          {isSending ? 'Signing in' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
