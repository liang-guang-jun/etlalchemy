"""Tests that every catalog prompt is documented and written in English."""

import re
from typing import Any

import pytest

from etlalchemy.app.mcp.server import MCPServer
from tests.app.mcp.support import get_prompt, list_prompts

NON_ASCII = re.compile(r"[^\x00-\x7f]")
CJK = re.compile(r"[\u4e00-\u9fff]")

PROMPT_ARGUMENTS: dict[str, dict[str, Any]] = {
    "catalog-overview": {},
    "inspect-table": {"catalog_id": "c-1", "schema_id": "s-1", "table_id": "t-1"},
    "find-field": {"term": "amount"},
    "rename-safely": {
        "catalog_id": "c-1",
        "schema_id": "s-1",
        "new_name": "revenue",
        "table_id": "t-1",
    },
    "import-catalog-workflow": {},
    "define-field": {
        "catalog_id": "c-1",
        "schema_id": "s-1",
        "table_id": "t-1",
        "field_name": "amount",
    },
    "review-vocabulary": {"domain_id": "d-1"},
    "explain-table": {"catalog_id": "c-1", "schema_id": "s-1", "table_id": "t-1"},
    "model-from-catalog": {"catalog_id": "c-1"},
    "review-model": {"model_id": "m-1"},
    "iam-access-review": {"tenant_id": "t-1"},
    "review-thread": {"thread_id": "th-1"},
    "resolve-discussion": {"thread_id": "th-1"},
    "draft-reply": {"thread_id": "th-1", "intent": "answer the question"},
    "open-thread-for-target": {"target_type": "table", "target_id": "t-1"},
}


async def test_prompts_are_listed(server: MCPServer) -> None:
    """All four workflow prompts are exposed."""
    names = {prompt.name for prompt in await list_prompts(server)}

    assert names == set(PROMPT_ARGUMENTS)


@pytest.mark.parametrize("name", sorted(PROMPT_ARGUMENTS))
async def test_prompt_description_is_english(server: MCPServer, name: str) -> None:
    """Descriptions are non-empty English text."""
    prompts = {prompt.name: prompt for prompt in await list_prompts(server)}

    description = prompts[name].description or ""
    assert description
    assert not NON_ASCII.search(description)
    assert not CJK.search(description)


@pytest.mark.parametrize("name", sorted(PROMPT_ARGUMENTS))
async def test_prompt_template_is_english(server: MCPServer, name: str) -> None:
    """Rendered templates contain ASCII English text only."""
    result = await get_prompt(server, name, PROMPT_ARGUMENTS[name])

    assert result.messages
    for message in result.messages:
        text = message.content.text
        assert text.strip()
        assert not NON_ASCII.search(text)
        assert not CJK.search(text)


async def test_prompt_arguments_use_snake_case(server: MCPServer) -> None:
    """Prompt arguments are snake_case."""
    for prompt in await list_prompts(server):
        for argument in prompt.arguments or []:
            assert argument.name == argument.name.lower()
            assert "-" not in argument.name
