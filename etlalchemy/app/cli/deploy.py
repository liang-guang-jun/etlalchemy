"""``etla deploy``: publishing the service to a hosting target.

Only the Databricks Apps target exists today, so the target is an explicit flag
instead of a positional argument: a later target adds its own flag and the
command keeps one shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from etlalchemy.app.config.loader import ConfigError, load_settings
from etlalchemy.app.deploy.errors import DeployError
from etlalchemy.app.deploy.runner import DeployOptions, deploy_databricks_apps

DEFAULT_UI_DIR = Path("dist/ui")
"""Bundle location relative to ``--source``."""

DEFAULT_TIMEOUT_SECONDS = 900
"""How long one deployment may take before the command gives up."""


def deploy(
    databricks_apps: Annotated[
        bool,
        typer.Option(
            "--databricks-apps",
            help=(
                "Deploy the service and its web UI as a Databricks App; "
                "needs the 'databricks' extra (uv sync --extra databricks)."
            ),
        ),
    ] = False,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile", "-p", help="Databricks CLI profile; defaults to the SDK default."
        ),
    ] = None,
    app_name: Annotated[
        str | None,
        typer.Option(
            "--app-name", help="Existing app to deploy to; defaults to deploy.databricks."
        ),
    ] = None,
    remote_path: Annotated[
        str | None,
        typer.Option(
            "--remote-path",
            help="Workspace folder the source is synced to; defaults to the user's home.",
        ),
    ] = None,
    config: Annotated[
        list[Path] | None,
        typer.Option(
            "--config",
            "-c",
            help=(
                "Configuration file uploaded next to the app; repeat it to layer files, "
                "a later one wins. config.default.yaml is uploaded first."
            ),
        ),
    ] = None,
    source: Annotated[
        Path,
        typer.Option(help="Repository root that is staged and deployed."),
    ] = Path(),
    dist_ui: Annotated[
        Path | None,
        typer.Option("--dist-ui", help="Built web bundle; defaults to <source>/dist/ui."),
    ] = None,
    build: Annotated[
        bool | None,
        typer.Option(
            "--build/--no-build",
            help=(
                "Run 'pnpm build' before deploying. The default builds only when the "
                "bundle is missing."
            ),
        ),
    ] = None,
    prune: Annotated[
        bool,
        typer.Option("--prune", help="Delete remote files that no longer exist locally."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Upload every file instead of only the changed ones."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the plan and stop before writing anything."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
    timeout: Annotated[
        int,
        typer.Option(help="Seconds to wait for the deployment to finish."),
    ] = DEFAULT_TIMEOUT_SECONDS,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the report as JSON."),
    ] = False,
) -> None:
    """Synchronise the source to a workspace folder and deploy the app."""
    if not databricks_apps:
        typer.echo("choose a deployment target: --databricks-apps", err=True)
        raise typer.Exit(2)
    root = source.expanduser().resolve()
    try:
        settings = load_settings().deploy.databricks
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc
    options = DeployOptions(
        profile=profile if profile is not None else settings.profile,
        app_name=app_name or settings.app_name,
        workspace_path=remote_path or settings.workspace_path,
        source=root,
        ui_dir=(dist_ui or root / DEFAULT_UI_DIR).expanduser().resolve(),
        config_files=tuple(path.expanduser().resolve() for path in config or ()),
        command=tuple(settings.command),
        health_timeout_seconds=settings.health_timeout_seconds,
        dry_run=dry_run,
        force=force,
        prune=prune,
        assume_yes=yes,
        build=build,
        timeout_seconds=timeout,
    )
    console = Console()
    try:
        report = deploy_databricks_apps(options, console=console)
    except DeployError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if as_json:
        typer.echo(json.dumps(report.to_json(), ensure_ascii=False))
        return
    if report.dry_run:
        console.print("[dim]dry run: nothing was uploaded[/dim]")
        return
    console.print(
        f"[green]deployed[/green] {report.app_name} "
        f"({report.uploaded} file(s), {report.bytes_uploaded} bytes, state {report.state})",
    )
    if report.url is not None:
        console.print(f"[bold]{report.url}[/bold]")
