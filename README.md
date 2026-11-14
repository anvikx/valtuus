# Junction 2026

FastAPI backend and React frontend behind Caddy. Every merge to `main` deploys to one VM.

```
browser --> Caddy (web) --+-- /api/* --> backend:8000 (FastAPI)
                          |
                          +-- else ----> /srv (React build)
```

## Documents

* [Interaction](docs/INTERACTION.md): the cart states, and who is bound to what.
* [Assumptions](docs/ASSUMPTIONS.md): what is not real in the prototype, and the known trust limits.
* [Next steps](docs/NEXT_STEPS.md): what comes after the prototype, and the path to AP2.

## Local commands

Needs `uv`, Node 22 and Docker.

| Command       | What it does                                         |
| ------------- | ---------------------------------------------------- |
| `make setup`  | Install backend and frontend deps                    |
| `make check`  | Lint, format, tests, types, build, infra (as CI)     |
| `make fmt`    | Format and autofix all code                          |
| `make dev-be` | Backend on http://localhost:8000 with reload         |
| `make dev-fe` | Frontend on http://localhost:5173, proxies `/api`    |
| `make up`     | Full stack in Docker on http://localhost             |
| `make down`   | Stop the Docker stack                                |

## Team rules

1. Work on a branch and open a PR. No direct push to `main`.
2. Run `make check` before every push.
3. Every merge to `main` deploys. Merge only what works.
4. Backend routes live only under `/api`.
5. The frontend calls the API only from `src/api.ts`.
6. Secrets live only in the server `.env`. Never commit them.
7. Before the demo, set the repo variable `DEPLOY_FROZEN=true` to stop deploys.
8. Follow the code rules in [CONTRIBUTING.md](CONTRIBUTING.md).

## CI/CD

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

## One time setup

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
   Private repos need a paid plan for this. "Use this template" does not copy it, so set it again
   in each new repo.
