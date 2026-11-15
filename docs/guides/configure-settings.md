# Configure the service

Change ports, databases and logging so the service runs the way your
environment expects, and know which file wins.

*Diátaxis type: how-to* · **Audience:** operators · **Time:** 15 minutes

## Before you start

A working install ([Run it locally](../getting-started/run-locally.md)) and
write access to the repository root, where the YAML files live.

## How the layers combine

```mermaid
flowchart TB
    a["config.example.yaml<br/>reference only"] -.->|"fallback when the<br/>default file is missing"| b["config.default.yaml"]
    b --> c["config.&lt;env&gt;.yaml<br/>default env: dev"]
    c --> d["--config extra.yaml<br/>repeatable, later wins"]
    d --> e["ETLALCHEMY_* environment variables"]
    env[".env next to pyproject.toml"] --> e
    e --> f["AppSettings"]
```

*Figure 1: Later layers win. Nested mappings merge key by key, so a layer that only sets `logging.level` keeps every other logging default.*

`config.example.yaml` is a template with every default spelled out; it is read
only when `config.default.yaml` does not exist. `config.default.yaml` is
git-ignored, which is why your local edits never show up in a diff.

## Pick the environment file

```bash
cp config.example.yaml config.default.yaml   # your everyday settings
cp config.example.yaml config.prod.yaml      # only the differences
uv run etla server                           # env "dev": config.dev.yaml
uv run etla server --env prod                # env "prod": config.prod.yaml
```

The environment name comes from `--env` or `ETLALCHEMY_ENV` and defaults to
`dev`, so a `config.dev.yaml` is applied automatically in a fresh checkout.
Extra files may also be passed per run; a later `--config` wins:

```bash
uv run etla server --config extra.yaml --config production.yaml
```

The CLI re-exports them through `ETLALCHEMY_CONFIG_FILES` so a `--reload`
worker loads the same files.

## Override one value with an environment variable

The prefix is `ETLALCHEMY_`, nesting is `__`:

```bash
export ETLALCHEMY_API__PORT=8080
export ETLALCHEMY_DATABASE__BACKEND=postgres
export ETLALCHEMY_LOGGING__LEVEL=DEBUG
export ETLALCHEMY_API__CORS_ORIGINS='["http://localhost:5173"]'
```

Lists and mappings take JSON. A `.env` file next to `pyproject.toml` is loaded
before the YAML, so `credential_ref: env:DEEPSEEK_API_KEY` and `${VAR}` placeholders
both resolve from it.

## Point contexts at their own database

Every context inherits the global `database` block; a context that declares its
own wins field by field.

```yaml
database:
  backend: postgres
  postgres_dsn: postgresql://etlalchemy:etlalchemy@localhost:55432/etlalchemy_test

ingestion:
  database:
    backend: postgres
    postgres_dsn: ${INGESTION_DB_DSN}
```

!!! warning "An empty block is not an omission"
    Leaving out `database:` shares the global datastore. Writing `database: {}`
    creates a *dedicated* datastore with defaults instead. Omit the key when you
    mean "share".

## Make the logs readable

```yaml
logging:
  level: INFO
  mode: stdout          # [asctime][LEVEL][logger] msg k=v
  color: true
  quiet: [uvicorn.access, httpx, sqlalchemy.engine]
  loggers:
    uvicorn: WARNING
```

`mode: json` switches to one JSON object per line for log collectors. `quiet`
silences a whole logger tree; `loggers` is applied afterwards and wins for the
same name.

## Verify the result

```bash
uv run etla server --log-level INFO
```

The first line the process logs is `server.configured` with `env`,
`config_files`, `host`, `port`, `mode` and `level` — that is the resolved
configuration, printed by the server itself.

## FAQ

**My variable is ignored.** It is probably not nested: `ETLALCHEMY_APIPORT` does
nothing, `ETLALCHEMY_API__PORT` is the form. Lists need JSON, not commas.

**The server starts on the wrong port.** `--port` beats `api.port` and exports
`ETLALCHEMY_API__PORT`, which beats the YAML.

**Can I configure by environment variable alone?** Yes — the files are optional.
That is how the tests run.

## See also

- [Configuration reference](../reference/configuration.md) — every key and default
- [CLI](../reference/cli.md) — `etla server` flags
- [Encrypt events at rest](enable-event-encryption.md) — the one security switch
