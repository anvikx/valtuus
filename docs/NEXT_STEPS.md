# Next steps

1. Standards: map the interface to the open standards for agent commerce when Valio Aimo chooses one.
2. Trust: mandates signed by the buyer and verified by Valio Aimo (the buyer's platform owns the mandate), the mandate hash in the order proof, an audit hash chain.
3. Identity: real login for the main user, approval roles, a "connect an agent" flow.
4. Orders: a real order API with stock reservation, cancel and change, a split over delivery dates.
5. Rules: more rule types as typed settings (limit per category or supplier, order days), templates per buyer type (hotel, school, hospital).
6. Agent experience: our own cards inside agent apps (MCP Apps), a callback in place of polling, a notice for a pending approval.
7. Seller value: unmet demand reports, a selling agent, memory of usual orders and of what a buyer means by a word.
8. Real buyer cases that are not built: a deputy approver, a monthly budget and cost per portion, a stock out after the order.

## Path to AP2

The path to AP2, with no change of states or rules.

| AP2 idea | Our part today | The step to AP2 |
|---|---|---|
| Intent mandate: what the agent may do | The buyer's mandate, stored and versioned at the gateway | The buyer signs the mandate, and the gateway verifies it |
| Cart mandate: the user approves one exact cart | The approval of a cart that cannot change, with a login and an audit record | The approval becomes a signature over the cart |
| Signed statements from the merchant | Signed offers and order confirmations (JWS) | The same content as verifiable credentials |
| Payment mandate | None. No payment in our scope | Outside the challenge |

Why we do not implement AP2 or UCP now: the brief puts the choice of standard out of scope, AP2 is built around payment, a mandate signed by the buyer needs keys on the buyer's side, and a partial copy of a specification is worse than an honest own design. Never call the prototype compliant with AP2 or UCP.
