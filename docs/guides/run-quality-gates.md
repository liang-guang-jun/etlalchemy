# Run the quality gates

Run ruff, mypy and pytest the way CI does, including the PostgreSQL integration
tests, before you report a change as done.

*Diátaxis type: how-to* · **Audience:** contributors · **Time:** 5 minutes

## Before you start

`uv sync` has run at least once.

## The one command

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q
```

```mermaid
flowchart LR
    ruff["ruff check<br/>+ format --check"] --> mypy["mypy<br/>strict, etlalchemy/"]
    mypy --> pytest["pytest<br/>tests/"]
    pytest --> ok{"all green?"}
    ok -->|"no"| fix["fix and rerun<br/>from the failing gate"]
    ok -->|"yes"| done["done"]
```

*Figure 1: The gates run in order because each one is cheaper than the next. Fix from the left: a lint error often explains a type error, and a type error often predicts a test failure.*

In VS Code the composite task **check backend** runs all three.

## What each gate enforces

| Gate | Scope | Notable rules |
|---|---|---|
| `ruff check` | `etlalchemy/` (tests excluded) | pydocstyle Google, exception names end with `Error` |
| `ruff format --check` | same | double quotes, 100 columns, LF |
| `mypy` | `etlalchemy/` only | `strict`, `no_implicit_reexport` (use `__all__`) |
| `pytest` | `tests/` | `--strict-markers`, warnings are errors, async tests need no marker |

## Run the PostgreSQL tests

The integration tests skip without a database:

```bash
docker compose -f docker/docker-compose.yml up -d --wait
TEST_DATABASE_URL=postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test \
  uv run pytest -q
```

They carry the `integration` marker; `uv run pytest -m integration` runs only
them, `-m "not integration"` runs the rest.

## Focus on one area

```bash
uv run pytest tests/catalog -q
uv run pytest tests/agent/test_runner.py -q -k approval
uv run mypy etlalchemy/vocabulary
```

!!! warning "A flaky `database is locked`"
    Running the whole `tests/app/mcp` directory occasionally raises
    `OperationalError: database is locked` on SQLite. It is a timing artefact of
    many concurrent event stores in one file, not a regression; rerun the
    directory before investigating.

!!! tip "Warnings are errors"
    `filterwarnings = ["error"]` means a deprecation warning fails the suite. A
    third-party warning is fixed by pinning or by an explicit `filterwarnings`
    entry in `pyproject.toml`, never by ignoring it in the test.

## FAQ

**Mypy fails on `casbin`.** It ships no stubs; the override in `pyproject.toml`
already ignores its missing imports.

**Ruff wants a docstring on a private helper.** Every module, class and function
needs one, including `__init__` and test helpers inside `etlalchemy/`.

**Can I run the gates from the frontend?** `pnpm lint && pnpm typecheck && pnpm test`
covers the UI; the Python gates never touch it.

## See also

- [Tests by context](../reference/data-model.md) — what lives where in `tests/`
- [Add a bounded context](add-a-bounded-context.md) — a change that touches every gate
- [Configuration](../reference/configuration.md) — pytest settings in `pyproject.toml`
