"""Tests for the catalog context MCP module."""


from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.server import MCPServer

EXPECTED_TOOLS = {
    "create_catalog",
    "change_catalog",
    "change_catalog_description",
    "discard_catalog",
    "create_schema",
    "change_schema",
    "change_schema_description",
    "discard_schema",
    "add_table",
    "change_table",
    "change_table_description",
    "discard_table",
    "add_field",
    "change_field",
    "change_field_comment",
    "remove_field",
    "rename_field",
    "search_fields",
}


async def test_catalog_registers_all_primitives() -> None:
    """One catalog.register call exposes every tool, resource and prompt."""
    server = MCPServer(Container())

    async def names() -> tuple[set[str], set[str], set[str], set[str]]:
        tools = {tool.name for tool in await server.mcp.list_tools()}
        resources = {str(resource.uri) for resource in await server.mcp.list_resources()}
        templates = {
            str(template.uri_template)
            for template in await server.mcp.list_resource_templates()
        }
        prompts = {prompt.name for prompt in await server.mcp.list_prompts()}
        return tools, resources, templates, prompts

    tools, resources, templates, prompts = await names()

    assert EXPECTED_TOOLS <= tools
    assert "catalog:///all" in resources
    assert "catalog:///{catalog_id}/schemas" in templates
    assert {"catalog-overview", "inspect-table", "find-field", "rename-safely"} <= prompts


async def test_server_name_covers_every_context() -> None:
    """The advertised server name is no longer catalog specific."""
    server = MCPServer(Container())

    assert server.name == "etlalchemy"
    assert server.mcp.name == "etlalchemy"
