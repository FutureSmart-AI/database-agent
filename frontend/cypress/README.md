# Cypress end-to-end suite

Covers the Database Agent (`/database-agent/…`) end to end: databases, chat,
charts, analytics, share, batch reports and usage.

Two tiers, and it matters which is which:

| Tier                         | Backend                | Gate                          | Runs in CI |
| ---------------------------- | ---------------------- | ----------------------------- | ---------- |
| `e2e/smoke/`                 | stubbed                | none                          | yes        |
| `e2e/nl2sql/`                | live, signed-in origin | `E2E_AUTHENTICATED=1`         | no         |
| `e2e/nl2sql/00-full-journey` | live, signed-in origin | the above **plus** `E2E_DB_*` | no         |

## Running it

The stubbed smoke runs against the static export, like CI:

```bash
bun run build && bun run preview        # terminal 1 — :3001
E2E_BASE_URL=http://localhost:3001 bun run test:e2e
```

The live suite needs a browser session on a `futuresmart.ai` origin, which is
what `bun run dev:secure` serves (see `docs/configuration.md`):

```bash
bun run dev:secure                      # terminal 1
E2E_BASE_URL=https://local.futuresmart.ai:4443 bun run test:e2e:live
```

Without `E2E_AUTHENTICATED`, every spec that needs a session is reported as
**pending**, not failed.

Unpinned, the suite opens the first NL2SQL agent the account can reach — owned
first, then shared, because an account can perfectly well own nothing and work
entirely inside agents other people shared with it. If that agent's databases
happen to be down, the configuration-panel specs skip themselves and say so;
pin a healthy agent to exercise them:

```bash
E2E_NL2SQL_AGENT_ID=<agent_id> bun run test:e2e:live
```

> **macOS note.** VS Code's integrated terminal exports
> `ELECTRON_RUN_AS_NODE=1`, which makes the Cypress binary start as Node and
> fail with `bad option: --no-sandbox`. The `test:e2e*` scripts strip it with
> `env -u`; call Cypress through them rather than `bunx cypress run` directly.

## The full lifecycle journey

`e2e/nl2sql/00-full-journey.cy.ts` is the one spec that writes. It creates its
**own** throwaway agent, drives every flow against it, and deletes it again:

1. create the agent through the wizard — connection tested, service provisioned,
   database connected and its schema read;
2. confirm it on Home with its database;
3. `Check all` reports the connection healthy;
4. save the database description, toggle a table's visibility, save a table
   description;
5. add a few-shot example and save it;
6. turn on Show sources / Follow-up / **Charts** and a suggested question, save,
   reload, confirm they persisted;
7. change a node's temperature under Advanced and save it;
8. enable both share channels, add an allowed domain, save the appearance,
   reload and confirm the round trip;
9. **ask a real question** — assert the executed SQL, the result rows, and a
   chart actually drawn in the chart viewer (recharts marks, not an empty
   surface);
10. find that question in Analytics' query log, with the overview charts drawn;
11. check the workspace Usage page;
12. create and delete a batch report;
13. delete the agent and confirm it left the workspace.

It needs a real database to point at:

```bash
bun run dev:secure    # in another terminal
E2E_BASE_URL=https://local.futuresmart.ai:4443 \
CYPRESS_DB_HOST=db.internal.example.com \
CYPRESS_DB_NAME=analytics \
CYPRESS_DB_USER=analytics_ro \
CYPRESS_DB_PASSWORD=… \
bun run test:e2e:live -- --spec cypress/e2e/nl2sql/00-full-journey.cy.ts
```

Use a **read-only** database user — the journey only ever reads. Missing any of
those four variables and the whole journey is pending rather than failing.

If a step fails, the ones after it are reported as skipped with the reason
("the journey stopped at …") instead of each failing on its own selector, and an
`after` hook deletes the agent through the API regardless — a failed run must
not leave an agent behind.

## Environment

| Variable                                                         | Effect                                                                                                  |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `CYPRESS_E2E_AUTHENTICATED`                                      | Required for everything but the boot smoke.                                                             |
| `CYPRESS_NL2SQL_AGENT_ID`                                        | Pins the agent the read-only agent-scoped specs open. Unset, the first NL2SQL agent in the workspace.   |
| `CYPRESS_E2E_ASK`                                                | Lets `07-conversations-chat` ask a real question (costs tokens).                                        |
| `CYPRESS_DB_HOST/NAME/USER/PASSWORD`                             | The database the lifecycle journey connects its throwaway agent to.                                     |
| `CYPRESS_DB_ENGINE`, `CYPRESS_DB_PORT`, `CYPRESS_DB_DESCRIPTION` | Optional; default to `postgresql`, the engine's port, and a generic description.                        |
| `CYPRESS_ASK_QUERY`                                              | The question the journey asks. Default asks for row counts as a chart.                                  |
| `CYPRESS_API_BASE`                                               | Where the cleanup request goes. Defaults to `NEXT_PUBLIC_BASE_URL`, then `http://localhost:4000/agent`. |
| `CYPRESS_E2E_AGENT_ID`                                           | Knowledge agent for the ported `document-preview` / `table-pagination` specs.                           |
| `CYPRESS_E2E_DATA_VIEW_AGENT_ID`                                 | Data View agent, when it differs from the above.                                                        |

`cypress.config.ts` also reads the unprefixed `E2E_*` names, so the environment
you already export for Playwright works unchanged.

## Run report

Every `cypress run` writes `cypress/reports/run-report.md` (and `.json`): totals,
a failure list with the first line of each error, and a per-spec table of every
test with its state and duration. Both files are gitignored — they are rebuilt on
each run.

## What the read-only specs will not do

Outside the lifecycle journey, the suite is deliberately non-destructive against
a workspace it does not own. It stops at the confirmation dialog or the unsaved
draft:

- no agent is created or deleted (the New agent wizard is walked and cancelled);
- no database is added, removed, or has its credentials overwritten;
- no answer feature, node config, appearance or share toggle is saved;
- no API key is issued and nobody is invited;
- no batch report is created or run.

The writes those specs _do_ perform are reversible or read-only by nature:
`Check all` and `Test connection` are probes the product runs on demand anyway,
and the one table-visibility toggle is flipped back inside the same test.

## Layout

```
cypress/
  support/
    gate.ts       describeAuthed / describeWithEnv — the session gate
    routes.ts     product routes + API matchers (regex, not globs — see the file)
    commands.ts   cy.nl2sqlAgentId / visitApp / visitAgent / shellReady / tab / dialog / toast
    stubs.ts      the fake backend, used by the boot smoke only
    report.ts     the after:run hook that writes cypress/reports/
  e2e/
    smoke/        stubbed; the only tier that runs without a session
    nl2sql/       the NL2SQL dashboard — 00 is the lifecycle journey, 01+ read-only
    legacy/       ported from e2e/*.spec.ts
```

## Relationship to the Playwright suite

`e2e/*.spec.ts` still runs in CI. All six specs there have Cypress equivalents
under `cypress/e2e/legacy/`, so the Playwright directory can be deleted once
this suite has run green against a real session for a release or two.

One deliberate difference: the ported `navigation.cy.ts` is gated, where the
Playwright original was not. Unauthenticated, those routes bounce to the SSO
origin, so the original was asserting against a cross-origin redirect to a host
that is not running — which times out rather than failing honestly.
`e2e/smoke/app-boot.cy.ts` is the ungated replacement.
