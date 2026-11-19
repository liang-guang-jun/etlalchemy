"""Tests for the tool surface of the catalog MCP server."""

from etlalchemy.app.mcp.server import MCPServer

from tests.app.mcp.support import list_tools

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
    "create_source_connection",
    "change_source_connection",
    "rotate_source_credential",
    "discard_source_connection",
    "import_source_catalog",
    "list_source_connections",
    "get_source_connection",
    "list_import_runs",
    "get_import_run",
    "list_source_kinds",
    "list_source_profiles",
    "inspect_source",
    "plan_import",
    "test_source_connection",
    "abandon_import_run",
    "create_domain",
    "change_domain",
    "discard_domain",
    "create_term",
    "change_term_color",
    "change_term_definition",
    "add_term_alias",
    "remove_term_alias",
    "rename_term",
    "move_term",
    "approve_term",
    "reopen_term",
    "deprecate_term",
    "reactivate_term",
    "link_term",
    "unlink_term",
    "discard_term",
    "list_domains",
    "get_domain",
    "list_terms",
    "get_term",
    "list_children",
    "list_descendants",
    "search_terms",
    "list_terms_for_target",
    "list_terms_for_table",
    "list_terms_for_field",
    "create_model",
    "change_model",
    "discard_model",
    "add_entity",
    "rename_entity",
    "change_entity_table",
    "remove_entity",
    "add_relationship",
    "change_relationship",
    "remove_relationship",
    "add_diagram",
    "rename_diagram",
    "change_diagram_order",
    "remove_diagram",
    "place_node",
    "move_node",
    "remove_node",
    "list_models",
    "get_model",
    "list_entities",
    "get_entity",
    "list_relationships",
    "get_relationship",
    "list_diagrams",
    "get_diagram",
    "list_nodes",
    "list_tenants",
    "list_users",
    "get_user",
    "list_groups",
    "list_group_members",
    "list_api_keys",
    "list_auth_providers",
    "list_audit_events",
    "create_thread",
    "add_comment",
    "edit_comment",
    "discard_comment",
    "resolve_thread",
    "reopen_thread",
    "discard_thread",
    "list_threads",
    "get_thread",
    "list_comments",
    "list_llm_providers",
    "get_llm_provider",
    "list_conversations",
    "list_conversation_messages",
}

READ_ONLY_TOOLS = {
    "search_fields",
    "list_source_connections",
    "get_source_connection",
    "list_import_runs",
    "get_import_run",
    "list_source_kinds",
    "list_source_profiles",
    "inspect_source",
    "plan_import",
    "test_source_connection",
    "list_domains",
    "get_domain",
    "list_terms",
    "get_term",
    "list_children",
    "list_descendants",
    "search_terms",
    "list_terms_for_target",
    "list_terms_for_table",
    "list_terms_for_field",
    "list_models",
    "get_model",
    "list_entities",
    "get_entity",
    "list_relationships",
    "get_relationship",
    "list_diagrams",
    "get_diagram",
    "list_nodes",
    "list_tenants",
    "list_users",
    "get_user",
    "list_groups",
    "list_group_members",
    "list_api_keys",
    "list_auth_providers",
    "list_audit_events",
    "list_threads",
    "get_thread",
    "list_comments",
    "list_llm_providers",
    "get_llm_provider",
    "list_conversations",
    "list_conversation_messages",
}

DESTRUCTIVE_TOOLS = {
    "discard_catalog",
    "discard_schema",
    "discard_table",
    "remove_field",
    "discard_source_connection",
    "abandon_import_run",
    "discard_domain",
    "discard_term",
    "remove_term_alias",
    "discard_model",
    "remove_entity",
    "remove_relationship",
    "remove_diagram",
    "remove_node",
    "discard_thread",
    "discard_comment",
}


async def test_read_only_tools_are_marked_read_only(server: MCPServer) -> None:
    """Parameterised reads are tools but advertise the read-only hint."""
    tools = {tool.name: tool for tool in await list_tools(server)}

    assert set(tools) == EXPECTED_TOOLS
    for name in READ_ONLY_TOOLS:
        assert tools[name].annotations.read_only_hint is True


async def test_every_tool_documents_its_parameters(server: MCPServer) -> None:
    """Each parameter carries a description for the model."""
    for tool in await list_tools(server):
        properties = tool.input_schema.get("properties", {})
        for property_name, schema in properties.items():
            assert schema.get("description"), f"{tool.name}.{property_name} has no description"


async def test_hints_mark_read_only_and_destructive_tools(server: MCPServer) -> None:
    """Reads and destructive commands carry the right hints."""
    tools = {tool.name: tool for tool in await list_tools(server)}

    for name in READ_ONLY_TOOLS:
        assert tools[name].annotations.read_only_hint is True
    for name in DESTRUCTIVE_TOOLS:
        assert tools[name].annotations.destructive_hint is True
    created = tools["create_catalog"].annotations
    assert created is None or created.destructive_hint is None


async def test_tools_are_named_verb_noun(server: MCPServer) -> None:
    """Tool names follow the verb_noun convention."""
    for tool in await list_tools(server):
        verb, _, noun = tool.name.partition("_")
        assert verb in {
            "create",
            "change",
            "discard",
            "add",
            "remove",
            "rename",
            "search",
            "rotate",
            "import",
            "get",
            "list",
            "inspect",
            "plan",
            "test",
            "abandon",
            "approve",
            "reopen",
            "deprecate",
            "reactivate",
            "link",
            "unlink",
            "move",
            "place",
            "edit",
            "resolve",
        }
        assert noun
