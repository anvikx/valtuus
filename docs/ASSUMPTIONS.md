# Assumptions

What is not real in the prototype.

* No order API in the mock: our gateway owns the order. An order is committed in the prototype's order ledger and is not sent to a Valio Aimo production system. No real stock decrease and no stock reservation.
* Stock is a snapshot at the time of the offer; the offer may be used for 15 minutes. Another buyer can take the stock before the approval. A signature proves the statement and its time, not that the stock is still there.
* Inside the 15 minutes the stock is not read again. The mock gives one quantity per delivery date.
* A split uses several products for one delivery date. It does not split one product over two dates.
* An outside agent sees what the mock API returns. No extra visibility filter (mentor).
* The `customer` field is ignored by the mock, so all buyers get the same price.
* One approver role (main user). No multi level approval, no approval by amount band.
* The approver can approve or reject, not edit lines.
* No cancel or change after the order is placed.
* A stock out is detected at request time, not by a background watcher (tier 3).
* Terminal stock 999999 = amount not known, and a date is not valid after closingTime: both are in the API documentation. For Stock products the amount is a known number (documentation). The value 9999999999 is used as a number, and the UI shows "In stock" for it. We do not claim "unlimited".
* An "equivalent" is only a substitution pair from Valio Aimo's product data. A product from the same category with the same claims is a "suggested alternative". Both need the same known allergen data and a person's sign off.
* A deputy approver, a monthly budget and a stock out after the order are not built.
* Demo clock: when DEMO_NOW is set, the gateway uses that time, gives it to the agent, and shows it on every page.
* UHT has no structured attribute in the product data (checked 14 Nov, 17,546 products). The attribute UHT is derived from the product name: the whole word "UHT", any case, in any of the 3 language names. The label warmTemperature is not used, because it is wrong for 7 of 17 UHT milk products.
* Delivery reliability and CO2 exist only for a part of the products. No data is shown as "no data", never as 0. The CO2 value is a product group average.
* A search returns at most 25 candidates, and a split uses the products of one offer call.
* Agent keys are created by seed. A "connect an agent" flow with OAuth is a next step.
* A reject blocks the same cart for 60 minutes. A longer or permanent block is a next step.
* Lines with different delivery dates may be in one cart. The webshop uses one cart per delivery date.
* The main user learns of a pending approval from the agent's link and from the inbox. A push or email notice is a next step.
* The agent learns a human decision by polling get_cart. A callback (webhook) is a next step.
* `request_text` and `clarifications` come from the agent. They are the agent's report of the buyer's words, not a verified fact. The gateway sees only the calls that reach it, not the agent's reasoning or its chat.
* A cart past its deadline expires when it is next read, not by a background job.
* The agent's own chat interface is not ours. The gateway returns structured data (options, estimates, reason sentences), and each agent app shows it in its own way.
* The signing key is our own key for the mock issuer "Valio Aimo (mock)". In production the gateway is Valio Aimo's own system and the key belongs to Valio Aimo.
* Currency is EUR only. All totals and limits are ex VAT.
* The gateway is one process. Its parts are separate behind interfaces, so a part can become its own service later.
* The demo has one buyer (a hotel). Another buyer type is another mandate on the same engine.

## Known trust limits

Each one is a next step in [NEXT_STEPS.md](NEXT_STEPS.md).

* Trust boundary: the buyer's mandate is stored at the Valio Aimo gateway and is not signed by the buyer. This follows today's webshop, which stores buyer roles. In a market with many sellers the buyer's platform can own the mandate, and Valio Aimo verifies it. The order confirmation names the mandate version, not a hash of it.
* The main user and the staff user are seeded logins. Next step: real identity (SSO) and approval roles.
* If the hash chain is not built: the audit is append only by code, not by cryptography.
* The gateway enforces the buyer's limit only for orders at Valio Aimo. A limit over several sellers belongs to the buyer's own agent platform.
* Explicit FREE_FROM is a valid allergen declaration, including products declaring only absence. Missing, empty, or malformed declarations remain UNKNOWN; CONTAINS and MAY_CONTAIN override conflicting FREE_FROM codes.
* Legacy catalog rows and offer snapshots have merged positive allergen codes with no recoverable declaration types. They are read as CONTAINS without changing their recorded status. A catalog reimport restores source types and translations. Legacy catalog rows have no language mapping; their display name remains available without inventing an English translation.
* Migration 0008 adds nullable allergen_declarations and names columns after main's session migrations and retains the allergen array for the previous image. Deploy the migration-skipping startup prerequisite before 0008; image rollback skips migrations and leaves the schema revision unchanged. See docs/CATALOG_ROLLOUT.md.
