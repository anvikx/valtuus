import { useEffect, type ReactElement } from 'react'

import { getSession } from '../api.ts'
import { isSignedOut, redirectToLogin } from '../session.ts'

interface ApprovalPageProps {
  readonly cartId: string
}

// The approve_url in a cart opens this page.
// TODO: GET /api/v1/carts/{id}, then POST .../approve or .../reject (main user session).
export function ApprovalPage({ cartId }: ApprovalPageProps): ReactElement {
  useEffect(() => {
    getSession().catch((error: unknown) => {
      if (isSignedOut(error)) {
        redirectToLogin()
      }
    })
  }, [])

  return (
    <main>
      <h1>Approve cart</h1>
      <p>Cart {cartId}</p>
    </main>
  )
}
