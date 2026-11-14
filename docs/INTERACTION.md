# Interaction

The cart states, and who is bound to what in each state.

| State | How it is reached | Who is bound to what |
|---|---|---|
| Inquiry | search_products, get_offers | Nobody. The gateway states: this is the fixed price for its price period, and this was the stock at issued_at. Stock is not reserved. |
| Cart AUTO | create_cart, policy = AUTO | Nobody yet. The agent may check out. |
| Cart PENDING_APPROVAL | create_cart, policy = HUMAN | Nobody yet. The main user can approve or reject. The agent may call checkout again: it succeeds only if the policy now gives AUTO (for example after the main user raised the limit). |
| DENIED | create_cart, policy = DENY | Ended. The reason codes say why. |
| ORDERED | checkout (policy AUTO) or approve | Both sides, in the prototype's order ledger: the buyer buys these lines at these prices for this delivery date. The signed order confirmation is the proof. The order is not sent to a Valio Aimo production system, because the mock has no order API. |
| REJECTED | The main user rejects | Ended and final, with the reason text. No order, nothing reserved. The same cart content cannot be sent again for REJECT_MEMORY_MINUTES. |
| EXPIRED | The order deadline passed (found at any read, checkout or approval), or a fresh check gave another price or too little stock | Ended. The agent must get new offers. |

Fixed price against offer expiry: the price is fixed for the whole period price_valid_from to price_valid_to. `valid_until` on an offer limits only how long the stock snapshot may be used (OFFER_TTL_MINUTES). Say this in the OpenAPI field descriptions.

After a reject (the role play asked this):
1. The cart is REJECTED and final. Nobody can approve it later, and the agent cannot check it out.
2. No order exists for it. Nothing was reserved. Earlier orders are not affected.
3. The record has a new line: who rejected, when, and the reason text.
4. The agent reads the result with get_cart and tells the buyer, with the reason.
5. The agent may make a new cart with another quantity, product or date. The policy checks that cart from the start. The same cart again gets DENY (PREVIOUSLY_REJECTED).

After a mandate change:
1. No stored cart changes its state, and no order is placed.
2. An AUTO cart: its next checkout runs the policy with the new version. If the result is HUMAN, the cart goes to PENDING_APPROVAL.
3. A pending cart: it stays pending. get_cart shows `current_decision` (advice). If it is AUTO, the agent may call checkout, and the policy decides again at that call.
4. The order confirmation records the mandate version that allowed the order.

An approval after the time limit:
1. After the order deadline (approve_before): no order. The cart is EXPIRED (CUTOFF_PASSED). The page shows the reason sentence and no buttons. The record has a line with who tried, and when. The agent gets new offers; the earliest delivery is then a later day, and the new cart goes through the policy from the start.
2. After the 15 minutes of the offer, but before the order deadline: the gateway reads price and stock again. Same price and enough stock: the order is placed. Else EXPIRED (PRICE_OR_STOCK_CHANGED).

