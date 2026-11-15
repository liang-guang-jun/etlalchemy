# Run it locally

Start the API and the MCP server from a clean checkout and confirm both answer.

*Diátaxis type: tutorial* · **Audience:** first-time contributors · **Time:** 15 minutes

## Before you start

Complete [Prerequisites](prerequisites.md): `uv` installed, the repository
cloned, `uv sync` run once.

## 1. Start PostgreSQL (optional)

```bash
docker compose -f docker/docker-compose.yml up -d --wait
```

The container listens on host port **55432** and creates the database
`etlalchemy_test` on first start (fresh volumes only).

## 2. Choose a configuration

```bash
cp config.example.yaml config.default.yaml
```

`config.default.yaml` is git-ignored on purpose: it is the file you edit. With no
file at all the built-in defaults are used — SQLite at `./catalog.db`.

!!! tip "Switch to PostgreSQL"
    Set `database.backend: postgres` and
    `database.postgres_dsn: postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test`,
    then run `docker compose … up -d --wait` first. The DSN user is `etlalchemy`,
    the password is `etlalchemy`.

## 3. Start the server

```bash
uv run etla server
```

```mermaid
flowchart LR
    boot["etla server"] --> cfg["load YAML layers<br/>+ ETLALCHEMY_*"]
    cfg --> log["configure_logging"]
    log --> uvicorn["uvicorn :8000"]
    uvicorn --> life["run_container<br/>init_resources"]
    life --> tables["view.create_table()"]
    tables --> apps["application.start()<br/>per context"]
    apps --> ready["/catalog … /mcp ready"]
```

*Figure 1: What happens between the command and the first request. Tables come before the applications start, because a projection must not miss an event that arrived while its table did not exist.*

The startup trail is logged on purpose (`lifecycle.start`,
`lifecycle.read_model.ready`, `lifecycle.resources.started`), so an empty log
means uvicorn never reached the lifespan.

## 4. Prove the API answers

```bash
curl -s http://localhost:8000/catalog/catalogs
```

`[]` means the service is up and the read model is empty. The interactive schema
is at <http://localhost:8000/docs>.

## 5. Prove MCP answers

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
```

| Answer | Meaning |
|---|---|
| `401` | the MCP server is mounted and authentication is working |
| `200` / `202` | the same, with a valid token or with `require_auth: false` |
| `307` | the mount is wrong — a trailing-slash redirect, not a handshake |
| `404` | `/mcp` is not served at all |

An IDE or the MCP Inspector needs a real client; see
[Connect an MCP client](../guides/connect-the-mcp-server.md).

!!! warning "MCP authentication is on by default"
    `mcp.require_auth` defaults to `true`, so every MCP request — including the
    handshake — needs a bearer token. Create one in
    [First administrator and token](first-admin.md) and add
    `-H "Authorization: Bearer $TOKEN"`, or set
    `ETLALCHEMY_MCP__REQUIRE_AUTH=false` for a local inspector only.

## 6. Stop cleanly

Press ++ctrl+c++. The lifespan closes the applications (`application.aclose()`)
and then the datastores, so the event store is not left with a half-written
transaction.

## FAQ

**The port is taken.** `uv run etla server --port 8080`, or set `api.port`.

**I want the code to reload.** `uv run etla server --reload`; the default comes
from `api.debug`.

**Where is my data?** SQLite: `./catalog.db`. PostgreSQL: the compose volume. The
event store tables are `<context>_application_events`, the read models are
`<context>_*`.

## See also

- [First administrator and token](first-admin.md) — the next tutorial
- [Configure the service](../guides/configure-settings.md) — ports, databases, logging
- [CLI](../reference/cli.md) — every flag of `etla server`
