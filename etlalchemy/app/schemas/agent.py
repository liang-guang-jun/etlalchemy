"""Request and response models of the agent endpoints.

The package may only import pydantic, the standard library and the projection
rows of the two contexts it serves, so both delivery layers share one model set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from etlalchemy.conversation.aggregates.types import clamp_content
from etlalchemy.conversation.projection.view import (
    ApprovalRow,
    ConversationRow,
    MessageRow,
    ResourceAccessRow,
    RunRow,
    ToolCallRow,
)
from etlalchemy.llm_config.projection.view import ProviderDetail, ProviderRow

# -- LLM providers ----------------------------------------------------------


class ProviderResponse(BaseModel):
    """One LLM provider without its shares."""

    provider_id: UUID
    """ID of the provider."""
    name: str
    """User-chosen name."""
    kind: str
    """Provider kind."""
    endpoint: str | None
    """Base URL, or ``None``."""
    credential_ref: str | None
    """External secret reference, or ``None``."""
    has_inline_credential: bool
    """Whether the provider holds an inline token instead of a reference."""
    default_model: str
    """Model used when a request does not name one."""
    options: dict[str, str]
    """Extra model options."""
    owner_user_id: UUID
    """Owner of the provider."""
    tenant_id: UUID | None
    """Tenant the provider is scoped to, or ``None``."""
    is_public: bool
    """Whether every user may use the provider."""
    is_system_default: bool
    """Whether the provider is the system-wide default."""
    created_at: datetime
    """Moment the provider was created."""

    @classmethod
    def from_row(cls, row: ProviderRow) -> ProviderResponse:
        """Builds the response from a read-model row."""
        return cls(
            provider_id=row.provider_id,
            name=row.name,
            kind=row.kind,
            endpoint=row.endpoint,
            credential_ref=row.credential_ref,
            has_inline_credential=row.has_inline_credential,
            default_model=row.default_model,
            options=row.options,
            owner_user_id=row.owner_user_id,
            tenant_id=row.tenant_id,
            is_public=row.is_public,
            is_system_default=row.is_system_default,
            created_at=row.created_at,
        )


class ProviderDetailResponse(ProviderResponse):
    """One LLM provider with its shares and default pointers."""

    shared_with_user_ids: list[UUID]
    """Users the provider is shared with."""
    shared_with_group_ids: list[UUID]
    """Groups the provider is shared with."""
    default_for_tenant_ids: list[UUID]
    """Tenants the provider is the default of."""
    default_for_user_ids: list[UUID]
    """Users the provider is the default of."""

    @classmethod
    def from_detail(cls, detail: ProviderDetail) -> ProviderDetailResponse:
        """Builds the response from the read-model detail."""
        base = ProviderResponse.from_row(detail.provider)
        return cls(
            **base.model_dump(),
            shared_with_user_ids=detail.shared_with_user_ids,
            shared_with_group_ids=detail.shared_with_group_ids,
            default_for_tenant_ids=detail.default_for_tenant_ids,
            default_for_user_ids=detail.default_for_user_ids,
        )


class ProviderCreate(BaseModel):
    """Body of ``POST /agent/llm-providers``."""

    name: str
    """User-chosen name."""
    kind: Literal["openai", "databricks_ai_gateway"] = "openai"
    """Provider kind."""
    endpoint: str | None = None
    """Base URL; required for ``databricks_ai_gateway``."""
    credential_ref: str | None = None
    """External secret reference."""
    token: str | None = Field(default=None, repr=False)
    """Inline credential, encrypted at rest."""
    default_model: str = ""
    """Model used when a request does not name one."""
    options: dict[str, str] = Field(default_factory=dict)
    """Extra model options."""
    tenant_id: UUID | None = None
    """Tenant the provider is scoped to."""
    is_public: bool = False
    """Whether the provider is visible to every user."""

    @model_validator(mode="after")
    def _validate_credential(self) -> ProviderCreate:
        """Requires exactly one credential source."""
        if (self.credential_ref is None) == (self.token is None):
            msg = "exactly one of credential_ref / token is required"
            raise ValueError(msg)
        return self


class ProviderPatch(BaseModel):
    """Body of ``PATCH /agent/llm-providers/{id}``."""

    name: str | None = None
    """New name."""
    endpoint: str | None = None
    """New endpoint."""
    default_model: str | None = None
    """New default model."""
    options: dict[str, str] | None = None
    """Complete new option mapping."""


class ProviderShareRequest(BaseModel):
    """Body of ``POST /agent/llm-providers/{id}/share``."""

    user_ids: list[UUID] = Field(default_factory=list)
    """Users the provider is shared with; replaces the previous list."""
    group_ids: list[UUID] = Field(default_factory=list)
    """Groups the provider is shared with; replaces the previous list."""


class ProviderDefaultRequest(BaseModel):
    """Body of ``POST /agent/llm-providers/{id}/default``."""

    scope: Literal["user", "tenant", "system"] = "user"
    """Scope the default pointer belongs to."""
    target_id: UUID | None = None
    """Tenant or user id; the caller and its tenant when omitted."""


class CredentialRotateRequest(BaseModel):
    """Body of ``POST /agent/llm-providers/{id}/rotate``."""

    credential_ref: str | None = None
    """External secret reference."""
    token: str | None = Field(default=None, repr=False)
    """Inline credential, encrypted at rest."""

    @model_validator(mode="after")
    def _validate_credential(self) -> CredentialRotateRequest:
        """Requires exactly one credential source."""
        if (self.credential_ref is None) == (self.token is None):
            msg = "exactly one of credential_ref / token is required"
            raise ValueError(msg)
        return self


# -- conversations ----------------------------------------------------------


class ResourceAccessResponse(BaseModel):
    """One resource read recorded on a message."""

    uri: str
    """URI of the resource."""
    size_bytes: int = 0
    """Size of the payload in bytes."""
    mime_type: str = ""
    """MIME type of the payload."""
    read_at: datetime | None = None
    """Moment the resource was read."""

    @classmethod
    def from_row(cls, row: ResourceAccessRow) -> ResourceAccessResponse:
        """Builds the response from a read-model row."""
        return cls(
            uri=row.uri,
            size_bytes=row.size_bytes,
            mime_type=row.mime_type,
            read_at=row.read_at,
        )


class ToolCallResponse(BaseModel):
    """One tool call recorded on a message."""

    tool: str
    """Name of the tool."""
    args_hash: str = ""
    """Digest of the arguments."""
    status: str = "ok"
    """Outcome of the call."""
    duration_ms: int = 0
    """Duration of the call in milliseconds."""
    error_code: str | None = None
    """Bracketed error category, or ``None``."""
    args_json: str = ""
    """Redacted, truncated JSON of the arguments."""
    result_preview: str = ""
    """Truncated text the tool returned."""

    @classmethod
    def from_row(cls, row: ToolCallRow) -> ToolCallResponse:
        """Builds the response from a read-model row."""
        return cls(
            tool=row.tool,
            args_hash=row.args_hash,
            status=row.status,
            duration_ms=row.duration_ms,
            error_code=row.error_code,
            args_json=row.args_json,
            result_preview=row.result_preview,
        )


class MessageResponse(BaseModel):
    """One message of a conversation."""

    message_id: UUID
    """ID of the message."""
    conversation_id: UUID
    """ID of the owning conversation."""
    role: str
    """Author of the message."""
    content: str
    """Body of the message."""
    interrupted: bool
    """Whether the producing stream was interrupted."""
    input_tokens: int
    """Prompt tokens billed by the provider."""
    output_tokens: int
    """Completion tokens billed by the provider."""
    created_at: datetime
    """Moment the message was written."""
    resources: list[ResourceAccessResponse] = Field(default_factory=list)
    """Resources read while producing the message."""
    tools: list[ToolCallResponse] = Field(default_factory=list)
    """Tool calls made while producing the message."""
    reasoning: str = ""
    """Thinking the model streamed before its answer."""

    @classmethod
    def from_row(cls, row: MessageRow) -> MessageResponse:
        """Builds the response from a read-model row."""
        return cls(
            message_id=row.message_id,
            conversation_id=row.conversation_id,
            role=row.role,
            content=row.content,
            interrupted=row.interrupted,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            created_at=row.created_at,
            resources=[ResourceAccessResponse.from_row(item) for item in row.resources],
            tools=[ToolCallResponse.from_row(item) for item in row.tools],
            reasoning=row.reasoning,
        )


class ConversationResponse(BaseModel):
    """One conversation."""

    conversation_id: UUID
    """ID of the conversation."""
    user_id: UUID
    """Owner of the conversation."""
    tenant_id: UUID | None
    """Tenant of the conversation, or ``None``."""
    title: str
    """Conversation title."""
    status: str
    """One of ``OPEN`` or ``DISCARDED``."""
    active_llm_provider_id: UUID | None
    """Selected provider, or ``None``."""
    message_count: int
    """Number of messages."""
    run_count: int
    """Number of runs."""
    created_at: datetime
    """Moment the conversation was created."""
    last_activity_at: datetime
    """Moment of the last activity."""

    @classmethod
    def from_row(cls, row: ConversationRow) -> ConversationResponse:
        """Builds the response from a read-model row."""
        return cls(
            conversation_id=row.conversation_id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            title=row.title,
            status=row.status,
            active_llm_provider_id=row.active_llm_provider_id,
            message_count=row.message_count,
            run_count=row.run_count,
            created_at=row.created_at,
            last_activity_at=row.last_activity_at,
        )


class ApprovalResponse(BaseModel):
    """One approval of a run."""

    approval_id: UUID
    """ID of the approval."""
    run_id: UUID
    """Run that asked for the decision."""
    tool: str
    """Tool waiting for the decision."""
    args_hash: str
    """Digest of the arguments."""
    reason: str
    """Reason shown to the approver."""
    status: str
    """One of ``pending``, ``approved`` or ``denied``."""
    requested_at: datetime
    """Moment the decision was requested."""
    decided_by: UUID | None = None
    """User that decided, or ``None``."""
    decided_at: datetime | None = None
    """Moment of the decision, or ``None``."""

    @classmethod
    def from_row(cls, row: ApprovalRow) -> ApprovalResponse:
        """Builds the response from a read-model row."""
        return cls(
            approval_id=row.approval_id,
            run_id=row.run_id,
            tool=row.tool,
            args_hash=row.args_hash,
            reason=row.reason,
            status=row.status,
            requested_at=row.requested_at,
            decided_by=row.decided_by,
            decided_at=row.decided_at,
        )


class RunResponse(BaseModel):
    """One agent run."""

    run_id: UUID
    """ID of the run."""
    conversation_id: UUID
    """Conversation that owns the run."""
    message_id: UUID
    """Assistant message the run produces."""
    status: str
    """One of ``running``, ``completed``, ``failed`` or ``interrupted``."""
    started_at: datetime
    """Moment the run started."""
    finished_at: datetime | None = None
    """Moment the run finished, or ``None``."""
    error: str | None = None
    """Failure message, or ``None``."""
    approvals: list[ApprovalResponse] = Field(default_factory=list)
    """Approvals the run requested."""

    @classmethod
    def from_row(cls, row: RunRow) -> RunResponse:
        """Builds the response from a read-model row."""
        return cls(
            run_id=row.run_id,
            conversation_id=row.conversation_id,
            message_id=row.message_id,
            status=row.status,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error=row.error,
            approvals=[ApprovalResponse.from_row(item) for item in row.approvals],
        )


class ConversationCreate(BaseModel):
    """Body of ``POST /agent/conversations``."""

    title: str = ""
    """Optional title."""
    llm_provider_id: UUID | None = None
    """Provider selected for the conversation, or ``None``."""


class ConversationPatch(BaseModel):
    """Body of ``PATCH /agent/conversations/{id}``."""

    title: str | None = None
    """New title."""
    llm_provider_id: UUID | None = None
    """New provider selection."""


class MessageCreate(BaseModel):
    """Body of ``POST /agent/conversations/{id}/messages``."""

    content: str
    """User message that starts the run."""
    llm_provider_id: UUID | None = None
    """Provider asked for explicitly, or ``None``."""
    auto_approve: bool = False
    """Run destructive tools without asking; the switch of the agent panel."""
    page_context: str | None = Field(default=None, max_length=2000)
    """Page the reader has open, spliced into the system prompt of the run.

    The floating widget sends the resource on screen so the agent knows what
    "these" refers to. It is never stored with the user message and never shown
    in the transcript.
    """

    @model_validator(mode="after")
    def _validate_content(self) -> MessageCreate:
        """Rejects a blank message body before it reaches the context."""
        if not clamp_content(self.content, 0).strip():
            msg = "content must not be blank"
            raise ValueError(msg)
        return self


class ApprovalDecisionBody(BaseModel):
    """Body of ``POST /agent/runs/{run_id}/approvals/{approval_id}:stream``."""

    approved: bool
    """Whether the tool call may run."""


class RunResultResponse(BaseModel):
    """Final result of one run."""

    run_id: UUID
    """ID of the run."""
    conversation_id: UUID
    """Conversation that owns the run."""
    message_id: UUID
    """Assistant message the run produced."""
    status: str
    """Final status of the run."""
    final_answer: str
    """Text of the last assistant message."""
    tools_called: int
    """Number of tool calls the run made."""
    resources_accessed: int
    """Number of resources the run read."""
    input_tokens: int
    """Prompt tokens billed by the provider."""
    output_tokens: int
    """Completion tokens billed by the provider."""
    error: str | None = None
    """Failure message, or ``None``."""
