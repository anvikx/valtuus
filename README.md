# Valtuus

Valtuus lets AI agents order food for professional kitchens safely: the agent proposes, the
buyer's mandate decides, every step is signed and logged.

Built for the Valio Aimo "Trusted Trade Agents" challenge at Junction 2026.
Live: https://junction.anvik.fi

> **Status: early prototype.** The gateway gives offers and makes carts with a policy decision.
> Search, checkout and approval are not complete. See [Status](#status).

## Why

A purchasing agent can search, compare and order faster than a person. That speed is the risk:
the rules for what an agent may buy cannot live inside the agent.

Valtuus puts the rules in a gateway on the wholesaler's side. Nobody has to trust the agent's
reasoning:

* The buyer sets the limits in a mandate and signs off what is outside them.
* The agent gets data that it can check: signed offers with prices, stock and deadlines.
* The wholesaler gets orders that it can accept: each order names the mandate version that
  allowed it.

## How it works

```
buyer --> buyer agent --(MCP or REST)--> Valtuus gateway --> Valio Aimo APIs
                                              |
                                  search, offers, cart
                                              |
                                  policy engine (no LLM)
                                              |
                    +-------------------------+-------------------------+
                    |                         |                         |
                  AUTO                      HUMAN                     DENY
           agent checks out        main user approves or        ended, with the
                    |               rejects on the approval        reason codes
                    |               page (human session)
                    +-------------------------+
                                              |
                        signed order confirmation + audit record
```

1. **Lookup.** The agent searches the catalog and gets offers: a fixed price for the price period
   and the stock at a stated time.
2. **Cart.** The agent creates a cart from offer IDs. It cannot send a price, a stock value or a
   date. The gateway reads them from its own stored offer.
3. **Decision.** The policy engine checks the cart against the buyer's mandate (spend limits,
   required attributes, forbidden allergens, deadlines) and returns AUTO, HUMAN or DENY. The
   decision is plain code with unit tests.
4. **Order.** Inside its authority the agent checks out. Outside it, only a person can approve,
   on the approval page. Words in the agent's chat are never an approval.
5. **Record.** Every step writes an audit record that both sides can read.

The cart states, and who is bound to what, are in [docs/INTERACTION.md](docs/INTERACTION.md).

## Connect your agent

| What          | Where                                                                |
| ------------- | -------------------------------------------------------------------- |
| MCP URL       | `https://junction.anvik.fi/api/mcp/`                                 |
| REST base URL | `https://junction.anvik.fi/api/v1`                                   |
| API docs      | https://junction.anvik.fi/api/docs and `/api/openapi.json`, no login |

The main user gives each agent its own key. Send it on every call, on MCP and REST:

```
Authorization: Bearer <agent key>
```

An agent key cannot approve or reject a cart, and cannot change the mandate. Only a person can.

For Claude Code, put this in `.mcp.json` and set `AGENT_KEY` in your shell, so the key is never
in the file:

```json
{
  "mcpServers": {
    "valtuus": {
      "type": "http",
      "url": "https://junction.anvik.fi/api/mcp/",
      "headers": {
        "Authorization": "Bearer ${AGENT_KEY}"
      }
    }
  }
}
```

Make the 4 calls in this order. REST paths are relative to the base URL.

| Step | MCP tool          | REST call                        | Result                             |
| ---- | ----------------- | -------------------------------- | ---------------------------------- |
| 1    | `search_products` | `GET /catalog/search?query=...`  | Product IDs. No price, no stock.   |
| 2    | `get_offers`      | `POST /offers`                   | Offer IDs, price and stock.        |
| 3    | `create_cart`     | `POST /carts`                    | The decision: AUTO, HUMAN or DENY. |
| 4    | `checkout`        | `POST /carts/{cart_id}/checkout` | Order confirmation. AUTO only.     |

* **Before step 1:** read the buyer's rules with `get_mandate` (`GET /mandate`).
* **HUMAN:** give the main user the cart's `approve_url`. Poll `get_cart`
  (`GET /carts/{cart_id}`) until the state is `ORDERED`, `REJECTED` or `EXPIRED`.
* **DENY:** stop. `reason_sentences` tell the buyer why.
* **Retries:** `create_cart` and `checkout` need an idempotency key (the `Idempotency-Key`
  header on REST, the `idempotency_key` argument on MCP). Send the same key again on a retry.
* **Errors:** every error has the body `{error, message, next_step}`. Follow `next_step`. A cart line with no `qty` also gets `reason_code: NEEDS_CLARIFICATION` and `missing`: ask the buyer, do not guess.

## Status

| Part                                                     | State   |
| -------------------------------------------------------- | ------- |
| Project skeleton, CI/CD with auto deploy and rollback    | Built   |
| Health endpoint `GET /api/health`                        | Built   |
| UHT attribute derived from product names                 | Built   |
| Offers, carts, policy engine                             | Built   |
| REST API, MCP tools, open OpenAPI file, main user login  | Built   |
| Product search                                           | Started |
| Checkout, orders, approve and reject                     | Started |
| Approval page, "Agent permissions" page, audit timeline  | Planned |
| Signed offers and order confirmations                    | Built   |

What is not real in the prototype, and the known trust limits, are listed openly in
[docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

## Quick start

Needs `uv`, Node 22 and Docker.

```sh
git clone https://github.com/anvikx/valtuus.git
cd valtuus
cp .env.example .env
make setup
make up
```

Open http://localhost. To run the parts on their own with reload, use `make dev-be` and
`make dev-fe`.

### Commands

| Command       | What it does                                         |
| ------------- | ---------------------------------------------------- |
| `make setup`  | Install backend and frontend deps                    |
| `make check`  | Lint, format, tests, types, build, infra (as CI)     |
| `make fmt`    | Format and autofix all code                          |
| `make dev-be` | Backend on http://localhost:8000 with reload         |
| `make dev-fe` | Frontend on http://localhost:5173, proxies `/api`    |
| `make up`     | Full stack in Docker on http://localhost             |
| `make down`   | Stop the Docker stack                                |

### Product data

The Valio Aimo product data is challenge data and is not part of this repository. The backend
downloads fresh files into `backend/data/` (gitignored) and loads them before accepting requests.
`VALIO_API_KEY` must be set in `.env`. A product download or parsing error prevents startup;
unavailable enrichment files are omitted from that import. With `make dev-be`, a code reload
also downloads the files again.

Inspect existing files without downloading or starting the app:

```bash
cd backend
uv run python -m app.commands.check_catalog
uv run python -m app.commands.check_catalog 460994
```

Pass `--data-dir PATH` to inspect files in a different directory.

## Architecture

FastAPI backend and React frontend behind Caddy. Every merge to `main` deploys to one VM.

```
browser --> Caddy (web) --+-- /api/* --> backend:8000 (FastAPI)
                          |
                          +-- else ----> /srv (React build)
```

```
backend/
  app/api/       REST routes under /api
  app/domain/    domain rules, no I/O
  tests/
frontend/
  src/api.ts     the only place that calls the backend
docs/            interaction, assumptions, next steps
scripts/         deploy script
```

## Documentation

* [Interaction](docs/INTERACTION.md): the cart states, and who is bound to what.
* [Assumptions](docs/ASSUMPTIONS.md): what is not real in the prototype, and the known trust
  limits.
* [Next steps](docs/NEXT_STEPS.md): what comes after the prototype, and the path to AP2.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the code rules. In short:

1. Work on a branch and open a PR. No direct push to `main`.
2. Run `make check` before every push.
3. Every merge to `main` deploys. Merge only what works.
4. Backend routes live only under `/api`.
5. The frontend calls the API only from `src/api.ts`.
6. Secrets live only in the server `.env`. Never commit them.
7. Before the demo, set the repo variable `DEPLOY_FROZEN=true` to stop deploys.

## Deployment

### CI/CD

```
PR ---------> backend (ruff, pytest)
              frontend (tsc, oxlint, prettier, build)
              infra (actionlint, shellcheck)

push main --> backend + frontend + infra --> images --> deploy
                                             |          |
                                             |          +- scp compose file + deploy.sh
                                             |          +- ssh: deploy.sh <sha>
                                             |                  healthy:   keep, save tag
                                             |                  unhealthy: roll back to last good tag
                                             +- push ghcr.io/<owner>/<repo>/{backend,web}:<sha>
```

`deploy` is skipped when the repo variable `DEPLOY_FROZEN` is `true`.

### Server (one VM)

1. Install Docker with the compose plugin.
2. Open ports 80 and 443.
3. Make a deploy user that can run `docker`, and add the public half of an SSH key to its
   `~/.ssh/authorized_keys`.
4. Make the deploy folder, for example `/opt/junction`, and put `.env` in it (see `.env.example`).
   Set `SITE_ADDRESS` to the domain to get HTTPS, and point the DNS A record to the VM.

### GitHub

1. Settings > Environments: create `production`.
2. Settings > Secrets and variables > Actions, add secrets:
   * `DEPLOY_HOST`: VM IP or host name
   * `DEPLOY_USER`: deploy user
   * `DEPLOY_SSH_KEY`: private half of the SSH key
   * `DEPLOY_PATH`: deploy folder, for example `/opt/junction`
3. Variables: `DEPLOY_FROZEN` set to `false` (set `true` to freeze).
4. Branch protection on `main`: require PR and the `backend`, `frontend` and `infra` checks.
   Private repos need a paid plan for this.

## License

Copyright (c) 2026 Anvik. All rights reserved. See [LICENSE](LICENSE).

## Acknowledgements

Valio Aimo for the challenge, the mock APIs and the product data. Junction for the hackathon.
