---
description: "Use when adding, changing or moving MCP contexts, tools, resources or prompts, or when touching etlalchemy/app/mcp/{registry,server,dev}.py. Covers the @mcp_context registry, namespace-free mounting and the per-context module contract."
applyTo: "etlalchemy/app/mcp/**/*.py"
---
# MCP Context Conventions

The MCP delivery layer is `etlalchemy/app/mcp/`. `registry.py` records context
factories, `server.py` mounts them, and each `<context>/` package owns its own
tools, resources and prompts. FastMCP is imported only by `etlalchemy/app/mcp/**`
and by the single `combine_lifespans` call in `etlalchemy/app/api/app.py`; context
packages and `etlalchemy/shared/` never import it, and `mcp/**` must never import
`etlalchemy.app.api`.

## Registration

- One package per context: `mcp/<context>/{__init__,tools,resources,prompts}.py`.
  Response models live in `etlalchemy/app/schemas/`, never in `mcp/<context>/`.
- `mcp/<context>/__init__.py` defines `INSTRUCTIONS` and decorates exactly one
  function:

  ```python
  @mcp_context("catalog", INSTRUCTIONS)
  def register(mcp: FastMCP, container: Container) -> None:
      tools.register(mcp, container)
      resources.register(mcp, container)
      prompts.register(mcp)
  ```

- `mcp_context` only appends `(name, instructions, register)` to the private
  `_FACTORIES` list and returns the function unchanged. **Importing a context
  must not build a `FastMCP` and must not touch the container**; everything
  happens in `build_contexts(container)`.
- A duplicate `name` raises `ValueError` at decoration time, i.e. while the
  module is imported. Registering the same context twice is a code error.
- Registration order is import order, so `server.py` decides the mount order
  through its imports. `from etlalchemy.app.mcp import catalog, ingestion` in
  `server.py` is the registration entry point and is marked "do not remove".

## Server and mounting

- `MCPServer.__init__` builds the parent, calls `build_contexts(container)` and
  `mount()`s one sub-server per context. It never names a context and never calls
  `register()` directly. `self.contexts` holds the mounted sub-servers for tests.
- **Never mount with a namespace.** Verified against fastmcp 4.1.6: a namespace
  turns `create_catalog` into `catalog_create_catalog`, rewrites `catalog:///all`
  into `catalog://catalog//all` and prefixes prompt names, which breaks every
  existing client and the resource URIs in the prompts. Introduce a namespace
  only together with a client migration and an explicit rename map.
- A mounted server's `instructions` never reach the client; only the parent's
  do. Keep the parent summary in `server.py` composed from the contexts'
  `INSTRUCTIONS` (a test asserts the composed text).
- A mounted server's lifespan runs for every client session of the parent, so
  mounting does not change when the container starts or stops.

## Context modules

- `tools.py` / `resources.py` expose `register(mcp, container)`; `prompts.py`
  exposes `register(mcp)`. Keep those signatures: the context `__init__.py` and
  the registry rely on them.
- Tools are coroutine functions with no request context, so the container is
  captured in closures and every application or view call is awaited. Each tool
  declares `name=`, `description=` and an
  `Annotated[..., Field(description=...)]` for every parameter, and hints as
  camelCase keys through `annotations=` (`{"readOnlyHint": True}` for
  parameterised reads, `{"destructiveHint": True}` for `discard_*` /
  `remove_field` / `abandon_import_run`).
- Wrap command bodies in `mcp_error_guard()` so domain errors become
  `[conflict]` / `[not_found]` / `[internal]` messages from `mcp/errors.py`.
- Resources answer `application/json` text through `etlalchemy.shared.utils.dump`
  and `uuid_or_none`, and return `null` or `[]` instead of raising for unknown or
  malformed ids. Collections are static resources, the rest are URI templates.
- Prompts are English ASCII templates that point at resource URIs and never embed
  data; descriptions and rendered text stay ASCII (a test enforces it).
- Adding a context needs the package plus one import line in `server.py`; a
  context that is not imported is silently absent from the server, so check
  `tests/app/mcp/test_registry.py::test_builtin_contexts_register_in_import_order`.

## Tests

- Tests live in `tests/app/mcp/` and use the `server` and `container` fixtures
  from `tests/app/mcp/conftest.py` plus the in-memory client helpers in
  `support.py`; assert exact sets (`EXPECTED_TOOLS`, `EXPECTED_STATIC`,
  `EXPECTED_TEMPLATES`) rather than counts alone. Client-side objects are
  `mcp_types.Tool` with snake_case hints (`tool.annotations.read_only_hint`) and
  `client.list_*` are coroutines; `client.instructions` is the only way to read
  the advertised text (`initialize_result` is `None` in-memory).
- A test that registers a dummy context must isolate the registry with
  `monkeypatch.setattr(registry, "_FACTORIES", [])` so the dummy never reaches
  `MCPServer` in other tests.
- The HTTP mount, the combined lifespan and the dev entry point are covered by
  `test_mount_with_lifespan.py`, `test_dev_entry.py` and `test_mcp_server.py`;
  keep them passing when the mounting code changes.
