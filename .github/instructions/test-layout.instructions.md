---
description: "Use when adding, moving, renaming or organizing Python tests. Unit tests are grouped by application (bounded context) first, e.g. tests/catalog/, mirroring etlalchemy/<context>/ — never by technical layer such as tests/aggregates/ or tests/unit/."
applyTo: "tests/**"
---
# Test Layout: Organize by Application

Unit tests are grouped by the **application (bounded context)** they belong to,
not by technical layer.

## Layout

- Mirror the context package: `etlalchemy/<context>/...` -> `tests/<context>/...`,
  keeping the inner package structure:
  - `etlalchemy/catalog/application.py` -> `tests/catalog/test_application.py`
  - `etlalchemy/catalog/aggregates/table.py` -> `tests/catalog/aggregates/test_table.py`
- Never create layer-first folders at the top of `tests/`: no `tests/aggregates/`,
  `tests/unit/`, `tests/integration/`.
- Integration and end-to-end tests also live under `tests/<context>/` and are
  distinguished by a pytest marker (for example `@pytest.mark.integration`), not by
  a separate top-level folder. Register new markers in `pyproject.toml`
  (`--strict-markers` is enabled).
- Keep package-level smoke tests (not tied to a context) at `tests/test_<name>.py`,
  for example `tests/test_version.py`.

## Delivery layer

`tests/app/` mirrors the assembly package `etlalchemy/app/` (it is a package mirror,
not a layer folder): `etlalchemy/app/mcp/registry.py` ->
`tests/app/mcp/test_registry.py`, `etlalchemy/app/api/routes/catalog.py` ->
`tests/app/test_api_catalog.py`, `etlalchemy/app/cli/` -> `tests/app/test_cli.py`.
The delivery tests keep their own `tests/app/conftest.py` (settings and container
fixtures) and, for MCP, `tests/app/mcp/conftest.py` plus `tests/app/mcp/support.py`
for in-memory client helpers.

## Importability

- Add an `__init__.py` to every test package directory
  (`tests/<context>/__init__.py`, `tests/<context>/aggregates/__init__.py`, ...).
  pytest's default `prepend` import mode uses the first directory without
  `__init__.py` as the import root, so equal module names (for example
  `test_table.py` in two contexts) would otherwise collide.

## Rules

- Move a test in the same change that moves the production module; the mirror must
  stay in sync.
- A test module imports from exactly one `etlalchemy/<context>/`; do not mix
  applications in one file.
- Context-specific fixtures live in `tests/<context>/conftest.py`; fixtures shared
  by several contexts live in `tests/conftest.py`.

## Example

```text
etlalchemy/
  catalog/
    application.py
    aggregates/
      catalog.py
      schema.py
      table.py
tests/
  conftest.py
  test_version.py
  catalog/
    __init__.py
    conftest.py
    test_application.py
    aggregates/
      __init__.py
      test_catalog.py
      test_schema.py
      test_table.py
```
