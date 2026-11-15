---
description: "Scaffold a new bounded context: aggregates, events, application use cases, mirrored tests and its MCP package"
argument-hint: "Context name and aggregate roots, e.g. 'warehouse: Warehouse, Source, Load'"
agent: "agent"
---
Scaffold the bounded context named in the chat arguments (context name plus its
aggregate roots). Follow the workspace instructions and the
[aggregate](../instructions/aggregates.instructions.md),
[test layout](../instructions/test-layout.instructions.md) and
[MCP context](../instructions/mcp-context.instructions.md) instruction files.

## Deliverables

1. `etlalchemy/<context>/aggregates/`
   - one module per aggregate root, plus `errors.py` and `__init__.py`
   - events as nested frozen dataclasses, commands bound with `@event(EventClass)`
   - no `trigger_event(...)` calls and no `apply()` methods on events
2. `etlalchemy/<context>/application.py`
   - `<Context>Application(AsyncApplication[UUID])` whose use cases are coroutines
   - cross-aggregate creation saved atomically with `self.save(parent, child)`
3. `etlalchemy/<context>/__init__.py` re-exporting aggregates, errors and application
4. Tests under `tests/<context>/`, mirroring the package layout, with an
   `__init__.py` in every test package directory:
   - aggregate behaviour, event replay and error paths
   - application use cases, including "failed use case persists nothing"
5. MCP delivery for the new context:
   - `etlalchemy/app/mcp/<context>/{__init__,tools,resources,prompts}.py`
   - one `@mcp_context("<context>", INSTRUCTIONS)` registration function in
     `__init__.py`, plus one import line in `etlalchemy/app/mcp/server.py`
   - extend the exact-set expectations in `tests/app/mcp/`

## Design rules

- Aggregates reference each other by `UUID` only; parents keep
  `dict[str, UUID]` name -> id registries.
- Validate before mutating, so a rejected command leaves `version` and
  `pending_events` untouched.
- Raise typed errors from `errors.py`; names end with `Error`.
- MCP follows
  [MCP context conventions](../instructions/mcp-context.instructions.md): the
  decorator only records the factory (no `FastMCP` at import time), contexts are
  mounted without a namespace, and tool/resource/prompt names stay stable.

## Finish

Run the gates and report them:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```
