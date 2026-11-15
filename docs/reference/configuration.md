# Configuration

Every configuration key, its default and how to override it.

*Diátaxis type: reference* · **Audience:** operators · **Prerequisites:** none

**On this page**

- [The shape of the file](#the-shape-of-the-file)
- [Top-level keys](#top-level-keys)
- [Per-context keys](#per-context-keys)
- [Agent keys](#agent-keys)
- [Environment overrides](#environment-overrides)
- [Validation](#validation)

## The shape of the file

One YAML document. Every key is optional; `config.example.yaml` lists every
default with its comment. The loader merges layers and validates the result into
`AppSettings` before anything starts, so a bad value fails the process, not a
request.

## Top-level keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `database.backend` | `sqlite` \| `postgres` | `sqlite` | event store and read model backend |
| `database.sqlite_path` | path | `./catalog.db` | file used by the SQLite backend |
| `database.postgres_dsn` | DSN | `""` | used by the PostgreSQL backend |
| `api.host` | str | `0.0.0.0` | bind address |
| `api.port` | int | `8000` | HTTP and MCP port |
| `api.debug` | bool | `false` | default of `--reload` |
| `api.prefix` | str | `/api` | path every router is mounted under; `""` serves the root |
| `api.ui_dir` | str | `dist/ui` | built SPA, relative to the project root; absent means API only |
| `api.health_path` | str | `/health` | liveness endpoint of the platform health check |
| `api.cors_origins` | list[str] | `[]` | allowed origins; empty disables CORS |
| `logging.level` | str | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `logging.mode` | `stdout` \| `json` | `stdout` | line format |
| `logging.color` | bool | `true` | ANSI colours, stdout only |
| `logging.quiet` | list[str] | `uvicorn.access`, `httpx`, … | loggers silenced entirely |
| `logging.loggers` | map[str, str] | `uvicorn: WARNING` | per-logger level, applied last |
| `mcp.require_auth` | bool | `true` | transport authentication of `/mcp` |
| `deploy.databricks.profile` | str | `""` | Databricks CLI profile of `etla deploy`; empty uses the SDK default |
| `deploy.databricks.app_name` | str | `etlalchemy` | existing app the deployment targets |
| `deploy.databricks.workspace_path` | str | `""` | folder the source is synced to; empty uses the caller's home |
| `deploy.databricks.command` | list[str] | `uv run uvicorn …` | command written into the generated `app.yaml` |
| `deploy.databricks.health_timeout_seconds` | int | `120` | how long the platform waits for `/health` |
| `cipher_key` | base64 str | unset | encrypts event state at rest |

`cipher_key` must decode to 16, 24 or 32 bytes; anything else is a validation
error at startup. See [Encrypt events at rest](../guides/enable-event-encryption.md).

## Per-context keys

Each context may override `database` field by field and owns a `projection`
block:

| Key | Default | Meaning |
|---|---|---|
| `<context>.projection.enabled` | `true` | run the projection for this context |
| `<context>.projection.tracking_table_name` | `<context>_projection_tracking` | shared tracking table |

Omitting `<context>.database` shares the global datastore. Writing an **empty**
`database: {}` creates a dedicated one — omit the key to share.

### `catalog`, `semantic`, `vocabulary`, `llm_config`

Only `database` and `projection`. All four have no tunable limits.

### `ingestion`

| Key | Default | Meaning |
|---|---|---|
| `ingestion.secrets.file_root` | `null` | base directory for relative `file:` references |
| `ingestion.source_kinds` | `["databricks", "postgres"]` | kinds the factory registers |

### `comment`

| Key | Default | Meaning |
|---|---|---|
| `comment.max_body_length` | `10000` | characters per comment |
| `comment.max_title_length` | `200` | characters per thread title |
| `comment.max_mentions_per_comment` | `20` | mentions in one comment |
| `comment.max_comments_per_thread` | `10000` | comments in one thread |
| `comment.soft_max_reply_depth` | `8` | advisory only; reports `depth_warning`, `0` disables |
| `comment.default_page_size` / `max_page_size` | `50` / `200` | paging |
| `comment.validate_target_exists` | `false` | reject a target that no view knows |
| `comment.enforce_target_tenant` | `false` | refuse a target in another tenant |
| `comment.read_requires_session` | `true` | reads need a bearer token |
| `comment.allow_multiple_threads` | `true` | one thread per target or many |
| `comment.target_types` | 14 entries | which target types may be commented on |

### `iam`

| Key | Default | Meaning |
|---|---|---|
| `iam.policy.reload_interval_seconds` | `1.0` | TTL of the in-memory Casbin policy |
| `iam.password_min_length` | `8` | minimum password length |
| `iam.max_api_keys` | `20` | live keys per user |
| `iam.api_key_grace_max_days` | `30` | maximum rotation grace |
| `iam.max_group_depth` | `64` | nesting limit |
| `iam.password_session_minutes` | `480` | session lifetime |
| `iam.oidc_session_minutes` | `480` | session lifetime |
| `iam.api_key_session_minutes` | `60` | session lifetime |
| `iam.api_key_pepper` | `null` | pepper for key hashes |
| `iam.secrets_file_root` | `null` | base for `file:` references |
| `iam.record_denied_authorizations` | `true` | write a denial to the audit log |
| `iam.bearer_token_prefix` | `iam_sess_` | token = prefix + session id |
| `iam.session_refresh_lead_minutes` | `5` | `refresh_at` offset |

### `conversation`

| Key | Default | Meaning |
|---|---|---|
| `conversation.max_message_chars` | `262144` | hard cap per message |
| `conversation.max_content_chars` | `65536` | cap per user prompt |
| `conversation.default_page_size` / `max_page_size` | `50` / `200` | paging |
| `conversation.run_stale_after_seconds` | `600` | a paused run stops blocking after this, `0` disables |

## Agent keys

| Key | Default | Meaning |
|---|---|---|
| `agent.mcp_transport` | `in_process` | `in_process` or `http` |
| `agent.mcp_url` | `http://127.0.0.1:8000/mcp` | only read by the http transport |
| `agent.request_timeout_seconds` | `30` | MCP request timeout |
| `agent.connect_retries` | `3` | connection attempts |
| `agent.history_limit` | `20` | stored messages replayed per run |
| `agent.auth.mode` | `service_account` | or `user_proxy` |
| `agent.auth.credential_ref` | `null` | `env:` reference of the service account |
| `agent.auth.tenant_id` | `null` | tenant the service account acts in |
| `agent.limits.max_tool_calls` | `25` | counts starts |
| `agent.limits.max_wall_clock_seconds` | `600` | exceeded → `interrupted` |
| `agent.limits.tool_timeout_seconds` | `60` | per call |
| `agent.limits.max_tool_output_chars` | `32000` | what the model reads |
| `agent.limits.max_tool_args_chars` | `2000` | browser preview |
| `agent.limits.max_tool_result_preview_chars` | `4000` | browser preview |
| `agent.limits.max_reasoning_chars` | `16000` | stored thinking |
| `agent.limits.token_budget` | `128000` | reported usage cap |
| `agent.tools.allowlist` / `denylist` | `null` / `[]` | what the model may see |
| `agent.tools.redact_argument_keys` | 9 entries | argument names masked in previews |
| `agent.tools.approval.default` | `deny` | unmatched destructive tool |
| `agent.tools.approval.rules` | `discard_* → require_approval` | first match wins |
| `agent.checkpoint.enabled` | `true` | LangGraph checkpointer |
| `agent.checkpoint.sqlite_path` / `postgres_dsn` | `null` | defaults to the global database |
| `agent.observability.mlflow.*` | disabled | `enabled`, `tracking_uri`, `experiment_name`, `run_tags` |

`agent.llm` is bootstrap-only: a provider created or synchronised on startup.
See [Use the agent](../guides/use-the-agent.md).

## Environment overrides

Every key can be set as `ETLALCHEMY_<PATH>`, upper-cased, with `__` between
levels:

| YAML | Variable |
|---|---|
| `api.port` | `ETLALCHEMY_API__PORT` |
| `database.backend` | `ETLALCHEMY_DATABASE__BACKEND` |
| `logging.level` | `ETLALCHEMY_LOGGING__LEVEL` |
| `agent.limits.max_tool_calls` | `ETLALCHEMY_AGENT__LIMITS__MAX_TOOL_CALLS` |
| `cipher_key` | `ETLALCHEMY_CIPHER_KEY` |

Lists and mappings take JSON (`ETLALCHEMY_API__CORS_ORIGINS='["http://localhost:5173"]'`).
Environment variables beat every file, and `.env` in the configuration directory
is exported first.

## Validation

| Situation | Result |
|---|---|
| unknown key | ignored by the YAML layer, rejected by `mypy` in code |
| wrong type | `ConfigError` at startup, message names the file |
| `cipher_key` of the wrong length | `ValidationError` → `ConfigError` |
| explicit `--config` file missing | `BadParameter`, exit code `2` |
| empty `database:` block | a dedicated datastore, not the global one |

## See also

- [Configure the service](../guides/configure-settings.md) — the layered-file workflow
- [CLI](cli.md) — flags that override these keys
- [Security model](../concepts/security.md) — what the IAM keys protect
