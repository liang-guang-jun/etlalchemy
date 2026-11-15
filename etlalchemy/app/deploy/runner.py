"""Orchestrating one ``etla deploy --databricks-apps`` run.

The run is a straight pipeline: resolve the target, build the staged tree, read
the remote folder, plan the difference, confirm it, upload the difference, record
the digests, then deploy and wait for the platform to report a state. Every step
reports to a ``rich`` console, and ``--json`` prints the returned report instead.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from rich import box
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Confirm
from rich.table import Table

from etlalchemy.app.deploy.auth import resolve_credentials
from etlalchemy.app.deploy.errors import DeployError, DeploymentFailedError
from etlalchemy.app.deploy.models import ChangeKind, DeployPlan, DeployReport, LocalFile
from etlalchemy.app.deploy.snapshot import (
    MANIFEST_NAME,
    Manifest,
    local_snapshot,
    plan_changes,
    staging_directories,
)
from etlalchemy.app.deploy.staging import StagingSpec, build_staging
from etlalchemy.app.deploy.workspace import AsyncWorkspaceApi, WorkspaceApi

TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "ERROR"})
"""Deployment states that end the wait loop."""

POLL_INTERVAL_SECONDS = 5.0
"""Seconds between two status reads of a running deployment."""

PLAN_ROWS = 15
"""Changed files listed before the table switches to a count."""


@dataclass(frozen=True, slots=True)
class DeployOptions:
    """Everything one deployment run needs."""

    profile: str
    """Databricks CLI profile name; empty for the SDK default."""

    app_name: str
    """App to deploy to; it has to exist already."""

    workspace_path: str
    """Folder the source is synchronised to; empty resolves to the user's home."""

    source: Path
    """Repository root the source is staged from."""

    ui_dir: Path
    """Directory holding the built SPA."""

    config_files: tuple[Path, ...]
    """Configuration files uploaded next to the source, in merge order."""

    command: tuple[str, ...]
    """Command written into the generated ``app.yaml``."""

    health_timeout_seconds: int
    """Seconds the platform waits for the health endpoint."""

    host: str = ""
    """Workspace URL of the profile, filled in when the credentials resolve."""

    dry_run: bool = False
    """Stop after printing the plan."""

    force: bool = False
    """Upload every file, even when the digests match."""

    prune: bool = False
    """Delete remote files that no longer exist locally."""

    assume_yes: bool = False
    """Skip the confirmation prompt."""

    build: bool | None = None
    """Build the frontend first; ``None`` builds only when the bundle is missing."""

    timeout_seconds: int = 900
    """How long to wait for the deployment to finish."""

    poll_interval_seconds: float = POLL_INTERVAL_SECONDS
    """Seconds between two status reads."""


def deploy_databricks_apps(options: DeployOptions, *, console: Console) -> DeployReport:
    """Resolves the profile and runs the deployment.

    Args:
        options: Target and behaviour of the run.
        console: Console the progress and the plan are rendered on.

    Returns:
        The report of the run.

    Raises:
        DeployError: When the profile, the bundle, an upload or the deployment
            itself fails.
    """
    credentials = resolve_credentials(options.profile)
    resolved = replace(options, host=credentials.host)

    async def run() -> DeployReport:
        api = AsyncWorkspaceApi(host=credentials.host, headers=credentials.headers)
        try:
            return await run_deploy(resolved, api=api, console=console)
        finally:
            await api.aclose()

    return asyncio.run(run())


async def run_deploy(
    options: DeployOptions,
    *,
    api: WorkspaceApi,
    console: Console,
) -> DeployReport:
    """Synchronises the staged source and deploys it.

    Args:
        options: Target and behaviour of the run.
        api: Workspace client; the tests pass an in-memory fake.
        console: Console the progress and the plan are rendered on.

    Returns:
        The report of the run.

    Raises:
        DeployError: When an upload fails, the deployment fails or the operator
            aborts, and ``AppNotFoundError`` when the app does not exist.
    """
    await api.get_app(options.app_name)
    workspace_path = options.workspace_path or await _default_workspace_path(api, options)
    _prepare_bundle(options, console)
    with tempfile.TemporaryDirectory(prefix="etla-deploy-") as directory:
        staged = build_staging(
            StagingSpec(
                source=options.source,
                ui_dir=options.ui_dir,
                config_files=options.config_files,
                command=options.command,
                health_timeout_seconds=options.health_timeout_seconds,
            ),
            Path(directory),
        )
        local = local_snapshot(staged.root)
        with console.status("Reading the remote workspace folder..."):
            remote = await api.list_tree(workspace_path)
            manifest = await _read_manifest(api, workspace_path)
        plan = plan_changes(local, remote, manifest, force=options.force)
        _render_plan(console, options, plan, workspace_path, staged.warnings)
        if options.dry_run:
            return DeployReport(
                profile=options.profile,
                host=options.host,
                app_name=options.app_name,
                workspace_path=workspace_path,
                plan=plan,
                uploaded=0,
                removed=0,
                bytes_uploaded=0,
                dry_run=True,
                warnings=staged.warnings,
            )
        _confirm(console, options, plan, workspace_path)
        await _create_directories(api, console, local, workspace_path)
        uploaded, uploaded_bytes = await _upload(api, console, staged.root, plan, workspace_path)
        removed = 0
        if options.prune:
            removed = await _prune(api, console, plan, workspace_path)
        if plan.uploads or plan.removals or not manifest.files:
            await api.write_file(
                f"{workspace_path}/{MANIFEST_NAME}",
                Manifest.from_snapshot(local).to_bytes(app_name=options.app_name),
            )
        deployment_id, state, url = await _deploy(api, console, options, workspace_path)
    return DeployReport(
        profile=options.profile,
        host=options.host,
        app_name=options.app_name,
        workspace_path=workspace_path,
        plan=plan,
        uploaded=uploaded,
        removed=removed,
        bytes_uploaded=uploaded_bytes,
        dry_run=False,
        deployment_id=deployment_id,
        state=state,
        url=url,
        warnings=staged.warnings,
    )


async def _default_workspace_path(api: WorkspaceApi, options: DeployOptions) -> str:
    """Returns the folder the source is synced to when none is configured.

    Args:
        api: Workspace client, asked for the profile's user name.
        options: Target of the run.

    Returns:
        ``/Workspace/Users/<user>/<app_name>``, a folder the caller owns.
    """
    user = await api.current_user()
    return f"/Workspace/Users/{user}/{options.app_name}"


def _prepare_bundle(options: DeployOptions, console: Console) -> None:
    """Makes sure the SPA bundle exists, building it when allowed.

    Args:
        options: Target of the run.
        console: Console the build message is rendered on.

    Raises:
        DeployError: When the bundle is missing and cannot be built.
    """
    index = options.ui_dir / "index.html"
    if options.build is False:
        if not index.is_file():
            msg = (
                f"the frontend bundle is missing in {options.ui_dir}; build it with "
                "'pnpm --dir frontend build' or drop --no-build"
            )
            raise DeployError(msg)
        return
    if options.build is True or not index.is_file():
        _run_frontend_build(options.source, console)
    if not index.is_file():
        msg = f"the frontend build produced no {index}; check the build output"
        raise DeployError(msg)


def _run_frontend_build(source: Path, console: Console) -> None:
    """Runs ``pnpm build`` in the frontend workspace.

    Args:
        source: Repository root.
        console: Console the build message is rendered on.

    Raises:
        DeployError: When pnpm is missing or the build fails.
    """
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        msg = "pnpm is required to build the frontend; install it or pass --no-build"
        raise DeployError(msg)
    frontend = source / "frontend"
    console.print(f"[dim]Building the frontend in {frontend}...[/dim]")
    result = subprocess.run(
        [pnpm, "--dir", str(frontend), "build"],
        check=False,
    )
    if result.returncode != 0:
        msg = f"'pnpm build' failed with exit code {result.returncode}"
        raise DeployError(msg)


async def _read_manifest(api: WorkspaceApi, workspace_path: str) -> Manifest:
    """Reads the digest manifest of the previous run.

    Args:
        api: Workspace client.
        workspace_path: Folder the app source lives in.

    Returns:
        The recorded manifest, or an empty one on the first deployment.
    """
    raw = await api.read_file(f"{workspace_path}/{MANIFEST_NAME}")
    return Manifest.empty() if raw is None else Manifest.parse(raw)


def _render_plan(
    console: Console,
    options: DeployOptions,
    plan: DeployPlan,
    workspace_path: str,
    warnings: tuple[str, ...],
) -> None:
    """Prints the deployment target, the difference and the warnings.

    Args:
        console: Console to write to.
        options: Target of the run.
        plan: Difference between the staged tree and the remote folder.
        workspace_path: Folder the app source lives in.
        warnings: Preflight warnings.
    """
    summary = Table(
        title=f"Deploy plan · {options.app_name}",
        title_justify="left",
        show_header=False,
        box=box.SIMPLE,
        pad_edge=False,
    )
    summary.add_column("Field", style="bold cyan", no_wrap=True)
    summary.add_column("Value")
    summary.add_row("Workspace", options.host or "unknown")
    summary.add_row("Folder", workspace_path)
    summary.add_row(
        "Files",
        f"{len(plan.changes)} local · {len(plan.uploads)} to upload · "
        f"{len(plan.unchanged)} unchanged",
    )
    summary.add_row("Upload", _format_bytes(plan.bytes_to_upload))
    removals = str(len(plan.removals))
    summary.add_row("Removals", removals if options.prune else f"{removals} (kept, pass --prune)")
    if options.force:
        summary.add_row("Mode", "force: every file is uploaded")
    if options.dry_run:
        summary.add_row("Mode", "dry run: nothing is written")
    console.print(summary)
    if plan.uploads:
        details = Table(box=box.SIMPLE, header_style="bold", pad_edge=False)
        details.add_column("Change", no_wrap=True)
        details.add_column("File")
        details.add_column("Size", justify="right")
        rows = plan.uploads[:PLAN_ROWS]
        for change in rows:
            style = "green" if change.kind is ChangeKind.ADDED else "yellow"
            details.add_row(
                f"[{style}]{change.kind}[/{style}]", change.path, _format_bytes(change.size)
            )
        hidden = len(plan.uploads) - len(rows)
        if hidden:
            details.add_row("", f"[dim]… and {hidden} more[/dim]", "")
        console.print(details)
    for warning in warnings:
        console.print(f"[yellow]warning[/yellow] {warning}")


def _confirm(
    console: Console,
    options: DeployOptions,
    plan: DeployPlan,
    workspace_path: str,
) -> None:
    """Asks the operator before anything is written.

    Args:
        console: Console the question is rendered on.
        options: Target of the run.
        plan: Difference that is about to be applied.
        workspace_path: Folder the app source lives in.

    Raises:
        DeployError: When the run is non-interactive without ``--yes``, or the
            operator declines.
    """
    if options.assume_yes:
        return
    if not console.is_terminal:
        msg = "refusing to deploy without confirmation in a non-interactive shell: pass --yes"
        raise DeployError(msg)
    question = (
        f"Upload {len(plan.uploads)} file(s) to {workspace_path} and deploy {options.app_name}?"
    )
    if not Confirm.ask(question, console=console, default=False):
        msg = "deployment cancelled"
        raise DeployError(msg)


async def _create_directories(
    api: WorkspaceApi,
    console: Console,
    local: dict[str, LocalFile],
    workspace_path: str,
) -> None:
    """Creates every staged directory below the app folder.

    Args:
        api: Workspace client.
        console: Console the progress is rendered on.
        local: Snapshot of the staged tree.
        workspace_path: Folder the app source lives in.
    """
    directories = staging_directories(local)
    if not directories:
        return
    with _progress(console, "Creating folders", len(directories)) as (progress, task):
        for directory in directories:
            await api.mkdirs(f"{workspace_path}/{directory}")
            progress.advance(task)


async def _upload(
    api: WorkspaceApi,
    console: Console,
    root: Path,
    plan: DeployPlan,
    workspace_path: str,
) -> tuple[int, int]:
    """Writes the added and updated files.

    Args:
        api: Workspace client.
        console: Console the progress is rendered on.
        root: Staged tree the content is read from.
        plan: Difference that is uploaded.
        workspace_path: Folder the app source lives in.

    Returns:
        The number of written files and their total size.
    """
    uploads = plan.uploads
    if not uploads:
        return 0, 0

    async def write(path: str, target: str, progress: Progress, task: TaskID) -> None:
        await api.write_file(target, (root / path).read_bytes())
        progress.advance(task)

    with _progress(console, "Uploading files", len(uploads)) as (progress, task):
        await asyncio.gather(
            *(
                write(change.path, f"{workspace_path}/{change.path}", progress, task)
                for change in uploads
            ),
        )
    return len(uploads), plan.bytes_to_upload


async def _prune(
    api: WorkspaceApi,
    console: Console,
    plan: DeployPlan,
    workspace_path: str,
) -> int:
    """Deletes the remote files that no longer exist locally.

    Args:
        api: Workspace client.
        console: Console the progress is rendered on.
        plan: Difference that is applied.
        workspace_path: Folder the app source lives in.

    Returns:
        The number of deleted files.
    """
    if not plan.removals:
        return 0
    with _progress(console, "Removing stale files", len(plan.removals)) as (progress, task):
        for path in plan.removals:
            await api.delete(f"{workspace_path}/{path}")
            progress.advance(task)
    return len(plan.removals)


async def _deploy(
    api: WorkspaceApi,
    console: Console,
    options: DeployOptions,
    workspace_path: str,
) -> tuple[str, str, str | None]:
    """Starts a deployment and waits for a terminal state.

    Args:
        api: Workspace client.
        console: Console the progress is rendered on.
        options: Target of the run.
        workspace_path: Folder the deployment reads the source from.

    Returns:
        The deployment id, its final state and the app URL.

    Raises:
        DeploymentFailedError: When the deployment fails, is cancelled or does
            not finish within the timeout.
    """
    deadline = time.monotonic() + options.timeout_seconds
    with console.status(f"Deploying {options.app_name}..."):
        deployment = await api.create_deployment(options.app_name, workspace_path)
        deployment_id = str(deployment.get("deployment_id") or "")
        if not deployment_id:
            msg = "the platform accepted the deployment but returned no deployment id"
            raise DeploymentFailedError(msg)
        state, message = _deployment_status(deployment)
        while state not in TERMINAL_STATES:
            if time.monotonic() >= deadline:
                msg = (
                    f"deployment {deployment_id} did not finish within "
                    f"{options.timeout_seconds}s (last state {state})"
                )
                raise DeploymentFailedError(msg)
            await asyncio.sleep(options.poll_interval_seconds)
            state, message = _deployment_status(
                await api.get_deployment(options.app_name, deployment_id),
            )
    if state != "SUCCEEDED":
        msg = f"deployment {deployment_id} ended in {state}: {message or 'no message'}"
        raise DeploymentFailedError(msg)
    app = await api.get_app(options.app_name)
    url = str(app.get("url") or "") or None
    if url is not None and not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return deployment_id, state, url


def _deployment_status(deployment: dict[str, object]) -> tuple[str, str]:
    """Extracts the state and message of a deployment.

    Args:
        deployment: Deployment object the API returned.

    Returns:
        The state (``PENDING`` when the platform reports none) and the message.
    """
    status = deployment.get("status")
    if not isinstance(status, dict):
        return "PENDING", ""
    state = str(status.get("state") or "PENDING")
    return state, str(status.get("message") or "")


@contextmanager
def _progress(
    console: Console,
    description: str,
    total: int,
) -> Iterator[tuple[Progress, TaskID]]:
    """Renders a progress bar for one phase.

    Args:
        console: Console the bar is rendered on.
        description: Task description.
        total: Number of steps.

    Yields:
        The running progress display and the id of its task.
    """
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        yield progress, progress.add_task(description, total=total)


def _format_bytes(value: int) -> str:
    """Formats a byte count for the plan table.

    Args:
        value: Number of bytes.

    Returns:
        A short human-readable size, for example ``1.4 MB``.
    """
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
