import type { ReactElement } from 'react'

interface ApprovalPageProps {
  readonly cartId: string
}

// The approve_url in a cart opens this page.
// TODO: GET /api/v1/carts/{id}, then POST .../approve or .../reject (main user session).
export function ApprovalPage({ cartId }: ApprovalPageProps): ReactElement {
  return (
    <main>
      <h1>Approve cart</h1>
      <p>Cart {cartId}</p>
    </main>
  )
}
