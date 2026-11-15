# Platform API

The routes that operate the platform: ingestion, IAM and the agent.

*Diátaxis type: reference* · **Audience:** API consumers · **Prerequisites:** a running server

**On this page**

- [Ingestion](#ingestion)
- [IAM](#iam)
- [Agent](#agent)
- [Authentication](#authentication)

## Ingestion

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/ingestion/connections` | register a source connection (`201`) |
| `GET` | `/api/ingestion/connections` | list live connections |
| `GET` | `/api/ingestion/connections/{connection_id}` | one connection |
| `PATCH` | `/api/ingestion/connections/{connection_id}` | change endpoint, name, options |
| `POST` | `/api/ingestion/connections/{connection_id}/rotate` | rotate the credential |
| `DELETE` | `/api/ingestion/connections/{connection_id}` | discard (`204`) |
| `GET` | `/api/ingestion/source-kinds` | kinds this deployment registers |
| `GET` | `/api/ingestion/source-profiles` | local credential profiles |
| `GET` | `/api/ingestion/connections/{connection_id}/inspect?catalog=&schema=&table=&limit=` | walk the source tree |
| `POST` | `/api/ingestion/connections/{connection_id}/test` | probe the source |
| `POST` | `/api/ingestion/connections/{connection_id}/plan` | diff without writing |
| `POST` | `/api/ingestion/connections/{connection_id}/import` | run the import (synchronous) |
| `GET` | `/api/ingestion/runs` | import history |
| `GET` | `/api/ingestion/runs/{run_id}` | one run |

`POST /ingestion/connections` body:

```json
{
  "name": "warehouse",
  "kind": "postgres",
  "endpoint": "localhost:55432",
  "credential_ref": "env:SOURCE_PG_PASSWORD",
  "token": null,
  "default_catalog": null,
  "options": {"user": "etlalchemy", "database": "etlalchemy_test"}
}
```

Exactly one of `credential_ref` / `token`, otherwise `422`. `plan` and `import`
share the body: `target_catalog_id` (required), `source_catalog`,
`include_schemas`, `include_tables` (per source schema), `schema_mapping`. The
import is synchronous by design — there is no progress feed.

## IAM

Session, identity, tenancy and authorization routes. All of them require a
bearer token except `/auth/*`, `/bootstrap` and `/authorize` on a fresh install.

### Authentication

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/iam/auth/token` | OAuth2 password form → `access_token` |
| `POST` | `/api/iam/auth/password` | JSON password login |
| `POST` | `/api/iam/auth/api-key` | exchange an API key for a session |
| `POST` | `/api/iam/auth/oidc` | exchange a verified `(issuer, subject)` |
| `POST` | `/api/iam/auth/refresh` | extend the current session |
| `POST` | `/api/iam/auth/logout` | revoke the session (`204`) |
| `GET` | `/api/iam/sessions/current` | the caller's session |
| `GET` | `/api/iam/bootstrap` | is a system administrator configured |
| `POST` | `/api/iam/authorize` | evaluate a permission for the caller |

`/api/iam/auth/token` takes `application/x-www-form-urlencoded` (`username`,
`password`, optional `scope=tenant:<uuid>`). Every response carries an opaque
`access_token` (`iam_sess_<session_id>`), `expires_at` and `refresh_at`.

### Tenants and users

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/iam/tenants` | create (`201`) |
| `GET` | `/api/iam/tenants` | list |
| `PATCH` | `/api/iam/tenants/{tenant_id}` | rename (`204`) |
| `DELETE` | `/api/iam/tenants/{tenant_id}` | discard, cascading sessions and rules |
| `GET` | `/api/iam/tenants/{tenant_id}/members` | members |
| `POST` | `/api/iam/tenants/{tenant_id}/members` | add a member (`204`) |
| `DELETE` | `/api/iam/tenants/{tenant_id}/members/{user_id}` | remove a member |
| `POST` | `/api/iam/users` | create a user (`201`) |
| `GET` | `/api/iam/users` | list |
| `GET` | `/api/iam/users/search?term=` | search |
| `GET` | `/api/iam/users/{user_id}` | one user |
| `PATCH` | `/api/iam/users/{user_id}` | change profile |
| `DELETE` | `/api/iam/users/{user_id}` | discard |
| `POST` | `/api/iam/users/{user_id}/system-admin` | grant the flag |
| `DELETE` | `/api/iam/users/{user_id}/system-admin` | revoke the flag |

### Identities and credentials

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/iam/users/{user_id}/identities/password` | attach a password (`201`) |
| `POST` | `/api/iam/users/{user_id}/identities/oidc` | attach an OIDC subject (`201`) |
| `GET` | `/api/iam/users/{user_id}/identities` | list identities |
| `PATCH` | `/api/iam/identities/{identity_id}` | change it (`204`) |
| `DELETE` | `/api/iam/identities/{identity_id}` | remove it |
| `POST` | `/api/iam/passwords/change` | change own password |
| `POST` | `/api/iam/passwords/reset` | reset someone's password |
| `POST` | `/api/iam/users/{user_id}/api-keys` | issue a key (`201`) |
| `GET` | `/api/iam/users/{user_id}/api-keys` | list keys |
| `POST` | `/api/iam/users/{user_id}/api-keys/{key_id}/rotate` | rotate (`201`) |
| `DELETE` | `/api/iam/users/{user_id}/api-keys/{key_id}` | revoke |

A credential change increments `Identity.credential_version`, which invalidates
sessions issued before it.

### Groups and permissions

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/iam/tenants/{tenant_id}/groups` | create a group (`201`) |
| `GET` | `/api/iam/tenants/{tenant_id}/groups` | list groups |
| `PATCH` | `/api/iam/groups/{group_id}` | rename (`204`) |
| `POST` | `/api/iam/groups/{group_id}/parent` | re-parent (cycle-safe) |
| `DELETE` | `/api/iam/groups/{group_id}` | discard |
| `GET` | `/api/iam/groups/{group_id}/members` | members |
| `POST` | `/api/iam/groups/{group_id}/members` | add a member |
| `DELETE` | `/api/iam/groups/{group_id}/members/{member_id}` | remove a member |
| `POST` | `/api/iam/tenants/{tenant_id}/groups/{group_id}/permissions` | grant |
| `DELETE` | `/api/iam/tenants/{tenant_id}/groups/{group_id}/permissions` | revoke |
| `POST` | `/api/iam/providers` | create an auth provider (`201`) |
| `GET` | `/api/iam/providers` | list providers |
| `PATCH` | `/api/iam/providers/{provider_id}` | change configuration |
| `DELETE` | `/api/iam/providers/{provider_id}` | discard |
| `GET` | `/api/iam/audit` | audit log |

## Agent

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/agent/llm-providers` | providers visible to the caller |
| `POST` | `/api/agent/llm-providers` | create one |
| `GET` | `/api/agent/llm-providers/{provider_id}` | detail |
| `PATCH` | `/api/agent/llm-providers/{provider_id}` | change endpoint, model, options |
| `POST` | `/api/agent/llm-providers/{provider_id}/rotate` | rotate its credential |
| `POST` | `/api/agent/llm-providers/{provider_id}/share` | share with users or groups |
| `POST` | `/api/agent/llm-providers/{provider_id}/default` | make it a default |
| `DELETE` | `/api/agent/llm-providers/{provider_id}` | discard |
| `GET` | `/api/agent/conversations` | the caller's conversations |
| `POST` | `/api/agent/conversations` | start one (`201`) |
| `GET` | `/api/agent/conversations/{conversation_id}` | one conversation |
| `PATCH` | `/api/agent/conversations/{conversation_id}` | title or pinned provider |
| `DELETE` | `/api/agent/conversations/{conversation_id}` | discard |
| `GET` | `/api/agent/conversations/{conversation_id}/messages` | transcript |
| `GET` | `/api/agent/conversations/{conversation_id}/approvals` | pending approvals |
| `GET` | `/api/agent/runs/{run_id}` | run status and trace |
| `POST` | `/api/agent/conversations/{conversation_id}/messages` | one synchronous turn |
| `POST` | `/api/agent/conversations/{conversation_id}/messages:stream` | one streamed turn (SSE) |
| `POST` | `/api/agent/conversations/{conversation_id}/messages/{message_id}/edit:stream` | edit and re-run |
| `POST` | `/api/agent/runs/{run_id}/approvals/{approval_id}:stream` | decide and resume (SSE) |

The streaming body carries `content`, optional `llm_provider_id` and
`page_context`, and `auto_approve`. `page_context` is spliced into the system
prompt of that run only: it is never stored with the message and never replayed.
The frame contract is in [SSE events](sse-events.md).

```mermaid
sequenceDiagram
    participant C as Client
    participant A as "Agent routes"
    participant R as "Run"
    C->>A: POST …/messages:stream
    A->>R: run starts
    R-->>C: message.completed (status awaiting_approval)
    R-->>C: done
    C->>A: GET …/approvals
    A-->>C: [approval]
    C->>A: POST …/approvals/{id}:stream {approved}
    A->>R: resume
    R-->>C: remaining frames + done
```

*Figure 1: A paused run closes its stream cleanly, so a client that reloaded can rebuild the card from the approvals route and resume the same assistant message.*

## Authentication

The token travels in `Authorization: Bearer <token>` only. The session id is
never accepted in a body, a query string or a path. Every rejection is the same
`401` with `WWW-Authenticate: Bearer` and the detail `invalid or expired token`,
so a client cannot enumerate sessions.

## See also

- [HTTP API](http-api.md) — catalog, semantic, vocabulary and comment routes
- [SSE events](sse-events.md) — the frames the agent streams
- [Security model](../concepts/security.md) — sessions, permissions, audit
