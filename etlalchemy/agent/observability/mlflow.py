"""Optional MLflow tracing of agent runs.

MLflow is imported lazily and only when the setting enables it, so a deployment
that leaves it off pays neither the import cost nor the dependency.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from etlalchemy.shared.logging import get_logger


@dataclass(frozen=True)
class MlflowSettings:
    """Where and how runs are recorded."""

    enabled: bool = False
    """Whether tracing is active."""
    tracking_uri: str = "http://localhost:5000"
    """MLflow tracking server URL."""
    experiment_name: str = "etlalchemy-agent"
    """Experiment the runs are logged to."""
    run_tags: Mapping[str, str] | None = None
    """Tags attached to every recorded run."""


@contextmanager
def trace_run(
    settings: MlflowSettings,
    *,
    run_id: str,
    inputs: Mapping[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Records one run in MLflow when tracing is enabled.

    Args:
        settings: Tracing configuration.
        run_id: Identifier of the run, used as the MLflow run name.
        inputs: Inputs recorded with the run.

    Yields:
        The active MLflow run, or ``None`` when tracing is disabled.
    """
    if not settings.enabled:
        yield None
        return
    log = get_logger("agent.observability")
    try:
        import mlflow
    except ImportError:
        log.warning("agent.mlflow.unavailable")
        yield None
        return
    try:
        mlflow.set_tracking_uri(settings.tracking_uri)
        mlflow.set_experiment(settings.experiment_name)
        with mlflow.start_run(run_name=run_id, tags=dict(settings.run_tags or {})) as run:
            if inputs:
                mlflow.log_params({key: str(value) for key, value in inputs.items()})
            yield run
    except Exception:
        log.exception("agent.mlflow.failed")
        yield None


def log_outcome(run: Any | None, *, status: str, tool_calls: int, tokens: int) -> None:
    """Records the outcome metrics of a finished run.

    Args:
        run: Active MLflow run, or ``None`` when tracing is disabled.
        status: Final status of the run.
        tool_calls: Number of tool calls the run made.
        tokens: Total tokens the run used.
    """
    if run is None:
        return
    try:
        import mlflow
    except ImportError:
        return
    mlflow.log_metrics({"tool_calls": tool_calls, "tokens": tokens})
    mlflow.set_tag("status", status)
