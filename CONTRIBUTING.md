# Code Rules

Rules for all code in this repo. Tools enforce some of them. Review checks the rest.

## Enforced by tools

Run `make check` before every push. CI runs the same steps.

| Area       | Tool       | Rules                                                                  |
| ---------- | ---------- | ---------------------------------------------------------------------- |
| Python     | ruff       | Line length 100, `E W F I N B UP SIM RET C90 RUF`, complexity 10       |
| Python     | ruff       | Type hints (`ANN`), no bool params (`FBT`), no private access (`SLF`)  |
| Python     | ruff       | No `print` left in code (`T20`). Tests may skip type hints             |
| Python     | pytest     | All tests pass. Every route lives under `/api` (`test_routes.py`)      |
| TypeScript | tsc        | `strict`, no unused locals or parameters, no `enum`                    |
| TypeScript | oxlint     | Warnings fail. No `any`, no `==`, braces always, hook rules            |
| TypeScript | oxlint     | Named exports only. `fetch` only in `src/api.ts`                       |
| TypeScript | prettier   | No semicolons, single quotes, trailing commas, width 100               |
| Infra      | actionlint | Workflow files are valid                                               |
| Infra      | shellcheck | `scripts/deploy.sh` passes                                             |
| GitHub     | settings   | PR with green checks before `main`. Needs a public repo or paid plan   |

Review checks the rules below that no tool can check, for example the layers, arrange/act/assert
in tests, and why-comments.

## Clean code

* Use braces on every `if`, `else` and loop, also for one line bodies.
* Split a call, object or parameter list over lines when it has 2 or more items. In Python, add a
  trailing comma so ruff keeps the split.
* One statement per line.
* Use early returns. Do not nest conditions deeply.
* Put a blank line between logical blocks (for example call, guard, return).
* Order a file as constants, types, helpers, then main logic.
* Give repeated or meaningful values a named constant. Values from a spec always get a constant
  (use `HTTPStatus.OK`, not `200`).
* Do not repeat the same structure more than twice. Extract a helper.

## Comments

* Explain why, not what. If a comment repeats the code, delete it.
* Improve the names before you add a comment.
* Comment non-obvious decisions, workarounds and platform quirks.
* When you fix a bug, say what was wrong and why the fix works.
* A TODO says what to do and when, for example
  `# TODO: replace polling with SSE when the stream endpoint exists`.
* Do not commit code that is commented out. Git keeps history.
* A test says why the behavior matters, not only what it checks.
* Use simple English. No em dashes.

## Names

* Names state intent. Prefer a verb for a function (`get_health`, `getHealth`).
* Keep function names under 30 characters.
* Booleans start with `is`, `has`, `should` or `can`.
* Use short names (`i`, `err`) only in small scopes.
* Use an enum or a union type, not a boolean parameter.

## Design

* Keep things private unless another module needs them. Python names start with `_`. TypeScript
  does not export what nothing imports.
* Respect the layers. Each layer calls only the layer directly below it.

```
App.tsx (UI) --> src/api.ts --> fetch --> Caddy /api/* --> FastAPI router --> service code
```

* The frontend calls the backend only from `src/api.ts`. Wire values (status strings, field names)
  stay in `src/api.ts`. The UI gets domain values.
* Every backend route lives under `/api`. Add routers in `create_app` with `prefix=_API_PREFIX`.
* Do not move or rename `GET /api/health`. The container health check and the deploy rollback
  depend on it.
* The backend runs one worker. In memory state must stay in one process.
* No speculative code. Add an interface, config or extension point only when something uses it.
* Handle error paths and edge cases in the same change, not later.

## TypeScript

* `const` by default, `let` only when you reassign. Never `var`.
* No `any`. Use `unknown` and narrow it.
* Named exports only (`vite.config.ts` is the exception, Vite needs a default export).
* `interface` for object shapes, `type` for unions.
* `readonly` for properties that do not change.
* Explicit return types on exported functions.

## Python

* Type hints on every function signature.
* `pathlib.Path`, not `os.path`.
* f-strings, not `%` or `.format()`.
* Tests use arrange, act, assert blocks with a blank line between them.

## Shell

* Quote and brace variables: `"${name}"`.
* Use `[[ ]]`, not `[ ]`.
* Put logic longer than a few lines in a function.
