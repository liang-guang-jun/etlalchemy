# CLI

`etla` is the supported entry point: serving the API and administering IAM.

*Diátaxis type: reference* · **Audience:** operators · **Prerequisites:** `uv sync`

## `etla server`

```bash
uv run etla server [--config FILE]... [--env NAME] [--host ADDR] [--port N] \
                   [--reload/--no-reload] [--log-level LEVEL] [--workers N]
```

| Option | Effect |
|---|---|
| `--config`, `-c` | extra configuration file; repeat to layer, later wins |
| `--env`, `-e` | configuration environment, e.g. `dev` or `prod` |
| `--host` | overrides `api.host`, exported as `ETLALCHEMY_API__HOST` |
| `--port` | overrides `api.port`, exported as `ETLALCHEMY_API__PORT` |
| `--reload/--no-reload` | defaults to `api.debug` |
| `--log-level` | uvicorn's own level |
| `--workers` | must be `1` together with `--reload` |

The command resolves the configuration once, configures logging, logs
`server.configured`, and hands control to uvicorn with the import string
`etlalchemy.app.main:app`. `ETLALCHEMY_CONFIG_FILES` is exported so a reloaded
worker reads the same files.

`etla --version` prints the package version; `etla` alone prints help.

## `etla iam`

Administration of the IAM context. Passwords are always read from a hidden
prompt — there is no password option.

| Command | Purpose |
|---|---|
| `etla iam bootstrap status` | is a system administrator configured |
| `etla iam bootstrap admin --email ADDR` | create the first system administrator |
| `etla iam login --email ADDR [--tenant NAME]` | obtain and store a session |
| `etla iam logout` | revoke the stored session |
| `etla iam admin create` | create another administrator |
| `etla iam admin grant` / `revoke` | manage the sysadmin flag |
| `etla iam admin list` | list administrators |
| `etla iam admin set-password` | set an administrator's password |
| `etla iam tenant create` / `list` | tenants |
| `etla iam tenant add-member` / `remove-member` | memberships |
| `etla iam provider create` / `disable` / `list` | auth providers |
| `etla iam self change-password` | change your own password |

Protected commands take `--session TOKEN` or read `$IAM_SESSION`.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | the command failed (domain or adapter error) |
| `2` | bad usage, including a missing `--config` file |
| `3` | a protected command ran without a session |

## Output

Add `--json` to any `iam` subcommand for machine-readable output. The CLI raises
the logging level to `WARNING` so `--json` output stays parseable; the server
command does the opposite and configures the level from the configuration.

!!! danger "Never pass a password on the command line"
    `bootstrap admin` and `set-password` prompt for it precisely so it cannot end
    up in shell history, a process listing or a CI log. For automation, pipe both
    lines on stdin.

## See also

- [First administrator and token](../getting-started/first-admin.md) — the bootstrap flow
- [Configure the service](../guides/configure-settings.md) — the file layers behind `--config`
- [Configuration](configuration.md) — every key the CLI can override
