import type { ReactElement } from 'react'

// Carts that wait for the main user.
// TODO: needs a list route for open carts. The backend has none yet (CartService.list_for_inbox).
export function InboxPage(): ReactElement {
  return (
    <main>
      <h1>Inbox</h1>
    </main>
  )
}
