import type { ReactElement } from 'react'

interface OrderPageProps {
  readonly orderId: string
}

// TODO: GET /api/v1/orders/{id} and show the confirmation with its trust mark.
export function OrderPage({ orderId }: OrderPageProps): ReactElement {
  return (
    <main>
      <h1>Order</h1>
      <p>Order {orderId}</p>
    </main>
  )
}
