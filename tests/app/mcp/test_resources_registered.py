"""Tests for the resource surface of the catalog MCP server."""

from etlalchemy.app.mcp.server import MCPServer

from tests.app.mcp.support import list_resource_templates, list_resources

EXPECTED_TEMPLATES = {
    "catalog:///{catalog_id}",
    "catalog:///{catalog_id}/schemas",
    "catalog:///{catalog_id}/schemas/{schema_id}",
    "catalog:///{catalog_id}/schemas/{schema_id}/tables",
    "catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}",
    "catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields",
    "ingestion:///connections/{connection_id}",
    "ingestion:///runs/{run_id}",
    "vocabulary:///domains/{domain_id}",
    "vocabulary:///domains/{domain_id}/terms",
    "vocabulary:///terms/{term_id}",
    "vocabulary:///terms/{term_id}/children",
    "vocabulary:///terms/{term_id}/descendants",
    "semantic:///models/{model_id}",
    "semantic:///models/{model_id}/entities",
    "semantic:///models/{model_id}/relationships",
    "semantic:///models/{model_id}/diagrams",
    "semantic:///models/{model_id}/diagrams/{name}",
    "semantic:///models/{model_id}/diagrams/{name}/nodes",
    "iam:///users/{user_id}",
    "iam:///groups/{tenant_id}",
    "comment:///threads/{thread_id}",
    "comment:///threads/{thread_id}/comments",
    "comment:///targets/{target_type}/{target_id}/threads",
    "llm:///{provider_id}",
}

EXPECTED_STATIC = {
    "catalog:///all",
    "ingestion:///connections",
    "ingestion:///runs",
    "vocabulary:///domains",
    "semantic:///models",
    "iam:///tenants",
    "iam:///users",
    "iam:///providers",
    "iam:///audit",
    "llm:///providers",
}


async def test_static_resources_are_listed(server: MCPServer) -> None:
    """The catalog and ingestion collections are static resources."""
    uris = {str(resource.uri) for resource in await list_resources(server)}

    assert uris == EXPECTED_STATIC


async def test_resource_templates_follow_the_hierarchy(server: MCPServer) -> None:
    """Every child collection and single object is an addressable template."""
    templates = {template.uri_template for template in await list_resource_templates(server)}

    assert templates == EXPECTED_TEMPLATES


async def test_resources_declare_json_mime_type(server: MCPServer) -> None:
    """Resources answer structured JSON."""
    for resource in await list_resources(server):
        assert resource.mime_type == "application/json"
    for template in await list_resource_templates(server):
        assert template.mime_type == "application/json"
