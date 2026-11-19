"""Tests of the optional MLflow tracing."""

from __future__ import annotations

import contextlib
import sys
import types
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.agent.observability.mlflow import MlflowSettings
from etlalchemy.agent.runtime import AgentRunner, RunRequest
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings
from langchain_core.messages import AIMessage

from tests.agent.support import FakeConversation, FakeMcpClient, UsageChatModel


class FakeMlflow(types.ModuleType):
    """Records the calls the tracing layer makes."""

    def __init__(self) -> None:
        """Starts with no recorded call."""
        super().__init__("mlflow")
        self.calls: dict[str, Any] = {}
        self.metrics: dict[str, Any] = {}

    def set_tracking_uri(self, uri: str) -> None:
        """Records the tracking URI."""
        self.calls["tracking_uri"] = uri

    def set_experiment(self, name: str) -> None:
        """Records the experiment."""
        self.calls["experiment"] = name

    @contextlib.contextmanager
    def start_run(self, run_name: str | None = None, tags: Any = None) -> Iterator[object]:
        """Records the run name."""
        self.calls["run_name"] = run_name
        self.calls["tags"] = tags
        yield object()

    def log_params(self, params: dict[str, str]) -> None:
        """Records the parameters."""
        self.calls["params"] = params

    def log_metrics(self, metrics: dict[str, Any]) -> None:
        """Records the metrics."""
        self.metrics.update(metrics)

    def set_tag(self, key: str, value: str) -> None:
        """Records a tag."""
        self.calls["tag"] = (key, value)


def runner_with_tracing(conversation: FakeConversation, tracing: MlflowSettings) -> AgentRunner:
    """Builds a runner whose model answers once."""
    model = UsageChatModel(
        message=AIMessage(
            content="answer",
            usage_metadata={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        ),
    )

    async def chat_model_factory(*_: object) -> object:
        return model

    return AgentRunner(
        client=FakeMcpClient(),  # type: ignore[arg-type]
        settings=AgentRuntimeSettings(limits=AgentLimits()),
        conversation=conversation,
        chat_model_factory=chat_model_factory,  # type: ignore[arg-type]
        checkpointer=None,
        tracing=tracing,
    )


async def test_enabled_tracing_records_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """An enabled tracer sees the run name, the inputs, the metrics and the tag."""
    fake = FakeMlflow()
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    runner = runner_with_tracing(
        FakeConversation(),
        MlflowSettings(enabled=True, tracking_uri="http://mlflow:5000"),
    )

    run = await runner.run(
        RunRequest(
            conversation_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            tenant_id=None,
            content="hello",
        ),
    )

    assert run.status == "completed"
    assert fake.calls["tracking_uri"] == "http://mlflow:5000"
    assert fake.calls["run_name"] == str(run.run_id)
    assert fake.calls["params"]["mode"] == "run"
    assert fake.metrics == {"tool_calls": 0, "tokens": 5}
    assert fake.calls["tag"] == ("status", "completed")


async def test_disabled_tracing_never_imports_mlflow(monkeypatch: pytest.MonkeyPatch) -> None:
    """With tracing off, MLflow is neither imported nor called."""
    fake = FakeMlflow()
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    runner = runner_with_tracing(FakeConversation(), MlflowSettings(enabled=False))

    await runner.run(
        RunRequest(
            conversation_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            tenant_id=None,
            content="hello",
        ),
    )

    assert fake.calls == {}
    assert fake.metrics == {}


@pytest.mark.integration
@pytest.mark.skipif(
    not __import__("os").environ.get("MLFLOW_TRACKING_URI"),
    reason="MLFLOW_TRACKING_URI is not set",
)
async def test_live_tracking_server_records_the_run() -> None:
    """Against a real tracking server the run is retrievable by its name."""
    import os

    import mlflow

    conversation = FakeConversation()
    run = await runner_with_tracing(
        conversation,
        MlflowSettings(
            enabled=True,
            tracking_uri=os.environ["MLFLOW_TRACKING_URI"],
            experiment_name="etlalchemy-agent-test",
        ),
    ).run(
        RunRequest(
            conversation_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            tenant_id=None,
            content="hello",
        ),
    )

    experiment = mlflow.get_experiment_by_name("etlalchemy-agent-test")
    assert experiment is not None
    found = mlflow.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string=f"tags.mlflow.runName = '{run.run_id}'",
    )
    assert not found.empty
