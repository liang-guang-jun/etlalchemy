# ETLAlchemy — workspace instructions

Event-sourced ETL metadata service. Python 3.13, managed with `uv`; the
`eventsourcing` library provides aggregates, events and the application
infrastructure, and the whole service is asynchronous on top of the asynchronous
infrastructure that is vendored in `etlalchemy/_vendor/eventsourcing/asyncio/`.

`eventsourcing` itself is installed from PyPI
(`eventsourcing[crypto,postgres]>=9.5.6,<9.6`); the distribution has no `asyncio`
package, so the asynchronous base classes (`AsyncApplication`, `AsyncProjection`,
`AsyncProjectionRunner`, `AsyncTrackingRecorder`, `AsyncSQLAlchemyDatastore`) are
imported from `etlalchemy._vendor.eventsourcing.asyncio.*` and
`PERSISTENCE_MODULE` is
`etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy`. The vendored modules are
verbatim copies of the `asyncio` branch of `liang-guang-jun/eventsourcing` except
for the import prefixes and the default topic, carry the upstream BSD-3-Clause
licence, and are excluded from `ruff` and `mypy` — never reformat them or add
docstrings, so a later upstream commit stays diffable (see
`etlalchemy/_vendor/eventsourcing/README.md`).

## Layout

- Bounded context per package: `etlalchemy/<context>/`
  - `aggregates/<name>.py` — one module per aggregate root, plus `errors.py`
  - `application.py` — `<Context>Application(AsyncApplication[UUID])` use cases
  - `projection/` — read model: `view.py` (interface + row dataclasses),
    `sqlalchemy.py` (the single async view), `projection.py` (`AsyncProjection` +
    `run_<context>_projection()`)
  - `__init__.py` — re-exports the public API (mypy `no_implicit_reexport`)
- `etlalchemy/shared/` — infrastructure adapters every context may reuse:
  `logging/`, the process-wide structured logging facade, `projection.py`, the
  `AsyncLoggedProjection` base every read-model projection extends, and `utils.py`
  with delivery helpers. It may only import the standard library, `eventsourcing`,
  `etlalchemy._vendor.eventsourcing` and `structlog`; contexts and the assembly layer
  may import it, never the other way round (`tests/shared/` holds its tests).
- Assembly layer in `etlalchemy/app/`: `bootstrap/` (the only assembly entry point:
  `factories.py`, `container.py`, `lifecycle.py` with `run_container`/`api_lifespan`,
  `settings.py` with `load_app_settings()`, all re-exported by `bootstrap/__init__.py`),
  `config/` (settings + YAML loader), `api/` (app factory + `routes/<context>.py`),
  `mcp/` (`registry.py` + a FastMCP server that mounts one package per context:
  `<context>/{tools,resources,prompts}.py`), `cli/` (typer app and the `server`
  command), `main.py` (uvicorn entry point).
- Tests mirror the context: `tests/<context>/...` (see
  [test-layout](./instructions/test-layout.instructions.md))
- Local infrastructure: `docker/docker-compose.yml` (Postgres 18, host port 55432,
  test DB `etlalchemy_test`). Integration tests use `TEST_DATABASE_URL` and the
  `integration` marker; run `docker compose -f docker/docker-compose.yml up -d --wait`.

## Quality gates (always run before reporting done)

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

- Tool config lives only in the root `pyproject.toml`.
- ruff excludes `tests`; it enforces pydocstyle (Google) on `etlalchemy/**`, so every
  module, class and method needs a docstring. Exception names must end with `Error`.
- mypy runs in strict mode over `etlalchemy/` only.
- pytest uses `--strict-markers` and `filterwarnings = ["error"]`, plus
  `asyncio_mode = "auto"` and `asyncio_default_fixture_loop_scope = "function"`, so
  `async def test_*` functions and async fixtures need no marker or CLI option.

## Domain rules

- Aggregates are independent; reference other aggregates by `UUID`, never by object.
- Events are frozen dataclasses declared inside the aggregate and bound to command
  methods with `@event(EventClass)`. Never call `self.trigger_event(...)` and never
  define `apply()` on an event class (see
  [aggregate conventions](./instructions/aggregates.instructions.md)).
- Validate before mutating; a failed command must leave version and pending events
  untouched.
- Cross-aggregate work (create a child aggregate and register its id in the parent)
  belongs in the application and is saved atomically: `self.save(parent, child)`.
- Deleting is a soft delete: `discard()` sets `_is_discarded`, every mutating command
  starts with `_ensure_not_discarded()` and raises `DiscardedError` (a `RuntimeError`)
  when the aggregate is already discarded. Discarding cascades to the records the
  parent tracks (`catalog.unregister_schema(...)`, `schema.unregister_table(...)`).
- Renaming a child updates both sides in one unit of work: the child records
  `Changed` and the parent records `SchemaNameChanged`/`TableNameChanged`, so the
  parent's name -> id registry never drifts.
- A field carries a `comment` (`Table.change_field_comment` → `FieldCommentChanged`,
  mirrored into `catalog_fields.comment`, added to older views on startup). It is
  metadata like a description, so an empty string clears it, an equal value records
  nothing, and a discarded table rejects it. The metadata-only MCP tools are
  `change_catalog_description`, `change_schema_description`,
  `change_table_description` and `change_field_comment`; HTTP exposes the same
  through `PATCH .../fields/{field_name}` with `comment` in `FieldPatch`.
- A schema or table is addressed by its registry name **or** by its id: the
  application resolves `UUID | str` (`CatalogApplication._schema` / `._table`) and the
  HTTP paths accept either, so the ids the create routes return stay valid after a
  rename. Unknown values raise `UnknownSchemaError`/`UnknownTableError` (404).
- Vocabulary terms form a tree: `Domain.terms` is keyed by full `path`
  (`Revenue/ARR`), `Term` carries `domain_id`, `parent_id` and `path`, and
  `(domain_id, path)` is unique among live rows. Renaming or moving a term repaths
  every descendant in one unit of work; a name may not be blank or contain `/`.
  The application addresses a term by path or id, while HTTP term URLs use ids only
  (a path cannot be one URL segment) and accept `parent` as a query/body value.
- A term carries an optional presentation `color` (`#rrggbb`, empty for none) stored on
  the aggregate and in `vocabulary_terms.color`. `Term.change_color` normalises the value
  (`normalise_color`, shorthand expanded, lowercase) and is allowed in every live status
  because colour is metadata, not content; only a discarded term rejects it. A malformed
  value raises `InvalidColorError`, which HTTP maps to 400 while MCP reports `[conflict]`
  like the other vocabulary validation errors. `create_table` adds the column to an
  existing `vocabulary_terms` table (SQLite `PRAGMA table_info` + `ALTER TABLE`, Postgres
  `ADD COLUMN IF NOT EXISTS`).
- A semantic model is ONE aggregate (`Model`) with internal entities: `entities`
  keyed by name, `relationships` keyed by id, `diagrams` keyed by name and
  `nodes` keyed by entity name. The `All` diagram is built by `__init__`, always
  shows exactly the entities of the model, rejects `place_node`/`remove_node` but
  accepts `move_node`. `EntityAdded` carries the initial `All` coordinates because
  the view cannot derive the diagonal layout; removing an entity cascades to the
  relationships and nodes that mention it, and `change_entity_table` is rejected
  while a relationship references the entity (`EntityInUseError`). Names reject a
  blank value and `/`; an all-`None` `change*` is a caller error (`ValueError`).
- A relationship's `from_refs`/`to_refs` are tuples of `(entity, field)` pairs that
  pair up by position, so their lengths must match; the application additionally
  checks every field against `CatalogView.list_fields` of the entity's table and
  reports a missing table as the catalog's `UnknownTableError` (404).
- IAM keeps six independent aggregates: `Tenant` (members), `User` (identity refs,
  memberships, sysadmin flag), `Identity` (PASSWORD / OIDC / API_KEY credentials),
  `Session`, `Group` (nesting, members, permission grants) and `AuthProvider`.
  Memberships are written on both sides in one `save(tenant, user)`; a credential
  change increments `Identity.credential_version`, and `authorize` rejects a session
  whose version is behind even before the projection revokes it. Group nesting is a
  `parent_group_id` on the child plus the parent's member list, both updated in one
  save; the application walks the ancestor chain through the event streams (not the
  view) so the cycle check is immediate. Only the read model writes the Casbin
  table; `CasbinAuthorizer` loads `iam_casbin_rules` into an in-memory enforcer and
  rebuilds it when the view's policy generation or the configured TTL changes. The
  IAM view writes a whole event cascade in one transaction (a single-row tracking
  table accepts one insert per transaction), so `discard_user`, `discard_tenant`,
  `discard_identity` and `discard_groups` also revoke sessions and delete rules.
  Audit rows are written with the event's own tracking row (`AuditEntry`); denied
  authorizations are recorded through a `Session.AccessDenied` event.
- OIDC stops at the verified `(issuer, subject)` pair: `iam/ports/oidc.py::OidcClient`
  is the host's protocol for the redirect, code exchange and JWKS check, the host
  resolves the client secret per call with `IamApplication.provider_client_secret`
  (only `client_secret_ref` is stored), and `authenticate_oidc` answers
  `UnboundOidcIdentity` for an unknown subject because there is no first-login
  auto-registration. A tenant-scoped provider is rejected unless the session acts in
  that tenant, and `update_auth_provider_config` refuses to change the issuer while
  identities are bound to it.

## Read model

- Views extend `etlalchemy._vendor.eventsourcing.asyncio.persistence.AsyncTrackingRecorder`
  through `AsyncSQLAlchemyTrackingRecorder`; there is exactly one view class per context and
  it serves SQLite (`aiosqlite`) and PostgreSQL (`psycopg`) alike. Every command
  awaits `self.transaction()` and writes the view change plus
  `self.insert_tracking_in_transaction(conn, tracking)` in that one transaction.
- SQLAlchemy Core is allowed only inside `projection/tables.py` and the
  `sqlalchemy.py` view: build DML with the statements of the SQLAlchemy ORM core and
  pick the upsert with `sqlite_insert`/`pg_insert` from `datastore.dialect_name`, then
  `await conn.execute(...)` on an `AsyncConnection`. `create_table()` creates the view
  tables with `conn.run_sync(metadata.create_all)` and the tracking table from the
  datastore metadata; never import SQLAlchemy in `view.py` or `projection.py`, never
  create an engine or session, and never compile SQL text for a raw cursor.
- Structure-changing commands are upserts, so replayed commands are idempotent.
- Deletes are soft: `discarded_at` (nullable `DateTime`) is set on `catalog_catalogs`,
  `catalog_schemas` and `catalog_tables` and cascades to children, while
  `catalog_fields` rows are deleted. Every `get_*`/`list_*`/`find_*`/`search_fields`
  lookup filters `discarded_at IS NULL`, and the `register_*` upserts reset it to `NULL`.
- Name uniqueness lives in the aggregates, not in the read model: the view tables have no
  `(parent, name)` unique constraint, so a discarded name can be reused. The
  `sa.Uuid`/`sa.DateTime(timezone=True)` column types let SQLAlchemy bind and return
  `UUID`s and datetimes on both dialects, so no manual bind conversion is needed.
- The projection extends `AsyncLoggedProjection` (an `AsyncProjection[View]`),
  dispatches with `eventsourcing.dispatch.singledispatchmethod` (not the `functools`
  one, because the handlers are coroutines) and is run by `AsyncProjectionRunner`
  (`run_<context>_projection()` returns it unstarted; await `start()` or use
  `async with`). Never create the tracking table by hand.
- The async recorders implement `subscribe()` for every backend, so no polling
  recorder topic is configured and `APPLICATION_RECORDER_TOPIC` stays unset.

## Table naming

- Every backend table this system creates must be snake_case, including the ones the
  framework derives. This applies to every future context as well, e.g.
  `warehouse_application_events` and `warehouse_projection_tracking`.
- Give each context explicit names: `<Context>Application.name = "<context>_application"`
  and `<Context>Projection.name = "<context>_projection"`. The Postgres factories build
  `<env name lower>_events` and `<env name lower>_tracking` from those names, so they
  decide the event store and tracking table names.
- Set `ProjectionSettings.tracking_table_name = "<context>_projection_tracking"` so the
  route view and the projection runner share the same tracking table.
- Name every view table `<context>_<plural>`, including the root entity table:
  `catalog_catalogs`, `catalog_schemas`, `catalog_tables`, `catalog_fields`,
  `semantic_models`, `semantic_entities`, `semantic_relationships`,
  `semantic_relationship_fields`, `semantic_diagrams`, `semantic_nodes`,
  `iam_tenants`, `iam_users`, `iam_tenant_members`, `iam_identities`,
  `iam_password_creds`, `iam_oidc_creds`, `iam_api_keys`, `iam_sessions`,
  `iam_groups`, `iam_group_members`, `iam_permission_grants`,
  `iam_auth_providers`, `iam_casbin_rules`, `iam_audit_log`.
- Both backends derive the same names from the environment: the async factory builds
  `<env name lower>_events` for the application recorder and `<env name lower>_tracking`
  for the projection `tracking_recorder`, so SQLite has no fixed `stored_events` /
  `tracking` tables any more.
- When adding a context, add a test that asserts the generated table names (see
  `tests/app/test_postgres_tables.py`).

## Assembly layer

- Dependency direction: `etlalchemy/app/**` may import any context; contexts must never
  import `etlalchemy.app` and must stay unaware of FastAPI, dependency-injector, YAML
  and pydantic-settings.
- Configuration layering (low to high): `config.example.yaml`, `config.default.yaml`,
  `config.<env>.yaml`, then `ETLALCHEMY_*` environment variables. Resolve a context's
  database only through `AppSettings.database_for(context)`.
- Datastores are synchronous `providers.Singleton`s (so they can be injected into
  sync providers) and a small async `providers.Resource` per datastore closes the
  engine on shutdown. The projection runners are async-generator resources that await
  `runner.start()` and `runner.stop()`. `bootstrap/lifecycle.py::run_container` awaits
  `container.init_resources()`, then creates the view tables and awaits
  `application.start()` per context; shutdown awaits `application.aclose()`, then
  `shutdown_resources()`. Every delivery layer (FastAPI `api_lifespan`, `mcp/dev.py`)
  uses it instead of repeating the wire/start/stop sequence.
- Applications are started by the lifecycle, not by their provider: `container
  .catalog_application()` only constructs the `AsyncApplication`.
- Routes use `@inject` + `Depends(Provide[Container.<provider>])`; never construct a
  container inside a route.
- Catalog writes are `POST`/`PATCH`/`DELETE`, addressed as
  `/catalogs/{catalog_id}/schemas/{schema}/tables/{table}/fields/{field_name}` where
  `{schema}` and `{table}` are a name or an id. `PATCH` takes a pydantic body and an
  all-`None` body is a 400 raised by the aggregate, `DELETE` answers 204, and
  `DiscardedError` is mapped to 409 next to the duplicate errors. A table patch also
  carries `description` (recorded by `Table.Changed`, mirrored into
  `catalog_tables.description`, and added to older views on startup), so tables own a
  description like catalogs and schemas.
- Catalog reads answer 404 through the same rule: `GET .../schemas/{schema}`,
  `.../schemas/{schema}/tables`, `.../tables/{table}` and `.../fields` resolve their
  path segments with the route helpers `_schema_row`/`_table_row`, which try the
  registry name first and then the id, and reject an id that belongs to another
  catalog or schema. `GET /catalog/search-objects?term=` searches catalogs, schemas,
  tables and fields by their own name (case-insensitive, at most 20 hits per level)
  and returns `kind` / `target_id` / `field_name` / `path`; the link picker uses it for
  cross-level suggestions. `GET /catalog/tables/{table_id}` answers the table plus the
  names of its schema and catalog, and `GET /catalog/tables/{table_id}/fields` lists its
  fields — both exist because the semantic entities only store a `table_id` — and both
  answer 404 for an unknown table id.
- Infrastructure construction belongs in `etlalchemy/app/bootstrap/factories.py`
  (`build_datastore`, `datastore_lifecycle`, the two view factories, small resolver
  functions); the container only declares providers and wiring — no `_`-prefixed
  helpers, no `isinstance` checks.
- Ingestion exposes the same operations over HTTP as over MCP:
  `GET /ingestion/source-kinds`, `GET /connections/{id}/inspect?catalog=&schema=&table=
  &limit=`, `POST /connections/{id}/test` and `POST /connections/{id}/plan`. The plan
  takes the import body (`ImportRequest`) because `include_tables` / `schema_mapping`
  are nested; it never writes. Read-model `ImportRunRow.created_at` is the column
  `ingestion_import_runs.created_at` (the MCP tool fills the same field from
  `ImportRun.created_on`), and it is what the history table shows as `Started`.
  `POST /connections/{id}/import` stays synchronous, so the UI has no progress feed.
- SQLAlchemy must not appear in `etlalchemy/app/**`.
- Authentication is one shared layer: `etlalchemy/app/auth/`
  (`SessionAuthenticator`, `AuthSession`, `InvalidTokenError`, scope helpers). A
  bearer token is opaque — `iam_sess_<session_id>` — and `SessionAuthenticator
  .authenticate` calls `IamApplication.validate_session` plus
  `effective_permissions`, so revocation, expiry and credential changes have one
  implementation for both delivery layers. Never add a second validator.
- FastAPI extracts the token with `OAuth2PasswordBearer(tokenUrl="/iam/auth/token",
  auto_error=False)` from `app/api/dependencies/auth.py`; `get_auth_session` answers
  every rejection with the same 401 `invalid or expired token` and
  `WWW-Authenticate: Bearer`, and `get_session_id` is the dependency routes use.
  Every `/iam/*` route except the login endpoints and `/iam/bootstrap` requires it;
  the session id never travels in a body, a query string or a path
  (`GET /iam/sessions/current` replaces the old path form). `POST /iam/auth/token`
  takes `OAuth2PasswordRequestForm` (so Swagger UI's Authorize button works) and
  carries the tenant as `scope=tenant:<uuid>`; the form scope never influences
  authorization.
- Logout revokes the session through an event, so an already-issued token stops
  working when the projection applies it, not synchronously: tests poll instead of
  asserting immediately.
- `etla` (`etlalchemy/app/cli/`) is the supported entry point. `etla server` takes a
  repeatable `--config`: the files are deep-merged on top of the YAML layers in the
  given order, so a later file wins, and they are re-exported through
  `ETLALCHEMY_CONFIG_FILES` so uvicorn reload workers read the same configuration.
  `--host`, `--port` and `--reload` override `api.host`, `api.port` and `api.debug`.
  `etla iam` (`app/cli/iam.py`) administers the IAM context: `bootstrap admin` is the
  only way to create the first system administrator, passwords are read from a hidden
  prompt (never an option), and protected commands take `--session` or `$IAM_SESSION`
  with exit code 3 when it is missing. The CLI raises the logging level to `WARNING`
  so `--json` output stays parseable.

## MCP server

- `etlalchemy/app/mcp/` exposes every bounded context over MCP at `/mcp`. The layer
  is a registry plus mounted sub-servers, so a context never edits `server.py`
  beyond one import line (see
  [MCP context conventions](./instructions/mcp-context.instructions.md)):
  `mcp/registry.py` holds `mcp_context(name, instructions)` and
  `build_contexts(container)`, each `mcp/<context>/__init__.py` decorates its
  `register(mcp, container)`, and `server.py` mounts one sub-server per context.
- Authentication is transport level: `mcp/auth.py::IamTokenVerifier` delegates to
  the shared `SessionAuthenticator` and is passed as `FastMCP(auth=...)` when
  `mcp.require_auth` is true (the default). The parent `http_app` enforces it for
  every mounted sub-server; the in-memory client does not, so tests disable the
  check in their config and supply a caller through the `mcp_session_resolver`
  provider. Tools read the caller with `current_session_id()` (claims of the
  verified `AccessToken`), never from a tool argument.
- The `from etlalchemy.app.mcp import catalog, ingestion` import in `server.py` is
  the registration entry point: a context that nobody imports is silently absent
  from the server. `mcp/errors.py` stays shared and maps every context's errors.
- Mount **without a namespace**. With fastmcp 4.1.6 a namespace renames tools
  (`catalog_create_catalog`), rewrites resource URIs to `catalog://catalog//all`
  and prefixes prompts, and a mounted server's `instructions` never reach the
  client, so the parent summary is composed from each context's `INSTRUCTIONS`.
- Tools are plain functions without a request context, so the container is
  captured in closures; `tools.py`/`resources.py` take `(mcp, container)` while
  `prompts.py` takes `(mcp)`.
- 107 tools (18 catalog, 14 ingestion, 26 semantic, 27 vocabulary, 10 comment,
  8 IAM, 2 conversation, 2 llm_config): the writes plus the
  parameterised reads (`search_fields`, `list_*`, `get_*`, `list_terms_for_*`,
  `inspect_source`, `plan_import`, `test_source_connection`) carry
  `readOnlyHint`, and `discard_*`, `remove_field`, `remove_term_alias`,
  `remove_entity`, `remove_relationship`, `remove_diagram`, `remove_node`,
  `abandon_import_run` carry `destructiveHint`. Whole-tree reads are resources
  under `catalog:///`, `ingestion:///`, `semantic:///` and `vocabulary:///`
  (9 static + 21 templates), answer `application/json` text, and return
  `null`/`[]` instead of raising for unknown or malformed ids.
- Prompts (11) are English templates that point at resource URIs and never embed
  data; descriptions and rendered text stay ASCII (a test enforces it).
- Tool errors are `RuntimeError(f"[conflict] …")`, `[not_found] …` or `[internal] …`
  from `errors.py`; FastMCP prefixes its own wrapper around the message.
- `create_app()` combines the FastAPI and FastMCP lifespans with
  `fastmcp.utilities.lifespan.combine_lifespans` and appends `mcp_app.routes` after the
  HTTP router. Do not `mount("/mcp", mcp_app)` with `http_app(path="/")`: that answers
  the bare `/mcp` endpoint with a 307 redirect instead of the MCP handshake error.
- Development tools such as the MCP Inspector start the server on their own, so they
  need the container lifespan: use the factory in `mcp/dev.py`
  (`fastmcp dev inspector etlalchemy/app/mcp/dev.py:create_mcp_server`). The CLI
  resolves a single attribute name (no dotted paths) and calls a factory with no
  arguments, so `...main.py:app.mcp_server.mcp` cannot work.

## Logging

- `etlalchemy/shared/logging/` is the only logging facade: `get_logger(name)`,
  `configure_logging(settings)`, `reset_logging()` (tests only) and the contextvars
  helpers `bind_context` / `bound_context` / `clear_context` / `get_context`.
- `configure_logging` accepts anything satisfying the shared `LoggingConfig` protocol
  (the pydantic `LoggingSettings` does) and must not import `etlalchemy.app`; it is
  idempotent, so `run_container` configures it before wiring and `etla` configures it
  before uvicorn starts.
- `logging.mode` is `stdout` (`[asctime][level][name] msg k=v`, the only mode where
  `color` applies) or `json` (one object per line). `merge_contextvars` stays first in
  the processor chain.
- Both logging paths share one renderer: the structlog chain ends with
  `ProcessorFormatter.wrap_for_formatter`, the renderer lives on the root handler's
  `ProcessorFormatter`, and `foreign_pre_chain` prepares stdlib records (uvicorn, httpx)
  for the same processor. Never append a renderer to the structlog chain and never let
  uvicorn install its own handlers: `serve()`/`main()` pass `log_config=None`, and
  `configure_logging` detaches the `uvicorn.*` loggers so they propagate to the root.
- Because third-party records can be silenced, the process logs its own startup
  trail: `etlalchemy.cli` logs `server.configured`/`server.start`/`server.stopped`,
  `run_container` logs `lifecycle.start`, `lifecycle.read_model.ready` (debug),
  `lifecycle.resources.started` and `lifecycle.stop`/`lifecycle.stopped`, and
  `create_app` logs `api.app.created` at debug. `app/main.py` configures logging at
  import time so the `--reload` child also covers uvicorn's own startup records.
- `logging.quiet` silences whole third-party trees via `level = CRITICAL + 1` (never
  `logging.disable`): silence one library there, silence one record level through
  `logging.loggers`, which is applied afterwards and wins for the same name.
- Use cases log `info` start/done for commands and `debug` for reads and per-column
  work; `import_from` wraps its body in
  `bound_context(run_id=..., connection_id=..., target_catalog_id=...)` and logs
  `exception` on failure.
- Projections log, views do not: `AsyncLoggedProjection` (`shared/projection.py`)
  wraps `process_event` and emits `projection.event` at debug (topic, notification id,
  originator id) plus `projection.event.failed` with the traceback before re-raising;
  `run_<context>_projection()` logs `projection.runner.started`. Subclasses register
  coroutine handlers on `dispatch_event`, never on `process_event`. The `sqlalchemy.py`
  views stay silent: they run once per projected event and once per read.
- Never log a credential: pass `credential="inline"` or the reference, never the token;
  `SourceConnection.token` and `SecretValue` stay out of every record.
- `RequestLoggingMiddleware` (`app/api/logging.py`) binds `request_id`/`method`/`path`
  per HTTP request, echoes `X-Request-ID`, and emits one `request` line per response
  (`status`, `duration_ms`) plus `request failed` on unhandled errors. It replaces the
  silenced `uvicorn.access`, so a read served straight from a view is still visible. It
  is raw ASGI on purpose: `BaseHTTPMiddleware` would buffer the MCP stream.
- `McpCallLoggingMiddleware` (`app/mcp/logging.py`, installed once on the parent in
  `MCPServer`) logs `mcp.tool` / `mcp.resource` / `mcp.prompt` with the primitive name
  and `duration_ms`, and `<event> failed` before re-raising.
- Logging tests call `reset_logging()` first (it restores the root handlers and levels,
  the third-party logger state, the structlog defaults and the `get_logger` cache) and
  then assert on `capsys` output or `structlog.testing.capture_logs()`; pass
  `processors=[structlog.contextvars.merge_contextvars]` when asserting bound context.

## Style

- `from __future__ import annotations` in every module with annotations.
- Google-style docstrings, imperative mood, first line ends with a period.
- Prefer explicit, typed code; annotate attributes assigned in `__init__`.
