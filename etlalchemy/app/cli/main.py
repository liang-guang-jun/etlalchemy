"""Typer entry point of the ``etla`` command line tool."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from etlalchemy import __version__
from etlalchemy.app.cli.iam import iam_app
from etlalchemy.app.cli.server import run_server
from etlalchemy.app.config.loader import ConfigError

app = typer.Typer(
    name="etla",
    help="ETLAlchemy command line interface.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(iam_app, name="iam")


def _show_version(value: bool) -> None:
    """Prints the package version and exits when ``--version`` is given."""
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            callback=_show_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Run the ETLAlchemy tools."""


@app.command()
def server(
    config: Annotated[
        list[Path] | None,
        typer.Option(
            "--config",
            "-c",
            help="Extra configuration file; repeat it to layer files, a later one wins.",
        ),
    ] = None,
    env: Annotated[
        str | None,
        typer.Option("--env", "-e", help="Configuration environment, for example dev or prod."),
    ] = None,
    host: Annotated[
        str | None,
        typer.Option(help="Bind address; overrides api.host."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(help="Bind port; overrides api.port."),
    ] = None,
    reload: Annotated[
        bool | None,
        typer.Option(
            "--reload/--no-reload",
            help="Restart workers on code changes; defaults to api.debug.",
        ),
    ] = None,
    log_level: Annotated[
        str | None,
        typer.Option(
            "--log-level",
            help=(
                "Overrides the uvicorn.* logger levels only; the format and the "
                "application loggers come from the logging settings."
            ),
        ),
    ] = None,
    workers: Annotated[
        int | None,
        typer.Option(help="Number of worker processes; cannot be combined with --reload."),
    ] = None,
) -> None:
    """Serve the ETLAlchemy HTTP API."""
    if reload and workers is not None and workers > 1:
        msg = "--workers cannot be combined with --reload"
        raise typer.BadParameter(msg, param_hint="--workers")
    try:
        run_server(
            config or (),
            env=env,
            host=host,
            port=port,
            reload=reload,
            log_level=log_level,
            workers=workers,
        )
    except ConfigError as exc:
        raise typer.BadParameter(str(exc)) from exc


def main() -> None:
    """Run the ``etla`` command line tool."""
    app()
