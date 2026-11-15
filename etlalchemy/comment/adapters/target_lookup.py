"""Composite target lookup of the comment context."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from etlalchemy.catalog.projection.view import CatalogView
from etlalchemy.comment.ports.target_lookup import TargetDescription
from etlalchemy.iam.projection.view import IamView
from etlalchemy.ingestion.projection.view import IngestionView
from etlalchemy.semantic.projection.view import SemanticView
from etlalchemy.vocabulary.projection.view import VocabularyView


class CompositeTargetLookup:
    """Resolves a target against the read model of the context that owns it.

    Only UUID-addressable targets are registered, so a name-keyed element
    (catalog field, semantic entity or diagram) is not resolved here.
    """

    def __init__(
        self,
        catalog_view: CatalogView,
        semantic_view: SemanticView,
        vocabulary_view: VocabularyView,
        ingestion_view: IngestionView,
        iam_view: IamView,
    ) -> None:
        """Wires the read models of the five upstream contexts."""
        self._catalog_view = catalog_view
        self._semantic_view = semantic_view
        self._vocabulary_view = vocabulary_view
        self._ingestion_view = ingestion_view
        self._iam_view = iam_view

    async def describe(self, target_type: str, target_id: UUID) -> TargetDescription | None:
        """Returns what the target is called, or ``None`` when it is unknown."""
        if target_type == "catalog":
            catalog = await self._catalog_view.get_catalog(target_id)
            if catalog is None:
                return None
            return TargetDescription(
                target_type=target_type,
                target_id=target_id,
                name=catalog.name,
                path=catalog.name,
                catalog_id=catalog.catalog_id,
            )
        if target_type == "schema":
            schema = await self._catalog_view.get_schema(target_id)
            if schema is None:
                return None
            catalog = await self._catalog_view.get_catalog(schema.catalog_id)
            catalog_name = catalog.name if catalog is not None else ""
            return TargetDescription(
                target_type=target_type,
                target_id=target_id,
                name=schema.name,
                path=f"{catalog_name} / {schema.name}",
                catalog_id=schema.catalog_id,
                schema_name=schema.name,
            )
        if target_type == "table":
            table = await self._catalog_view.get_table(target_id)
            if table is None:
                return None
            return await self._table_description(table)
        if target_type == "field":
            field = await self._catalog_view.get_field(target_id)
            if field is None:
                return None
            table = await self._catalog_view.get_table(field.table_id)
            if table is None:
                return None
            base = await self._table_description(table)
            return TargetDescription(
                target_type=target_type,
                target_id=target_id,
                name=field.name,
                path=f"{base.path} / {field.name}",
                catalog_id=base.catalog_id,
                schema_name=base.schema_name,
                table_name=base.name,
                field_name=field.name,
            )
        if target_type == "semantic_model":
            model = await self._semantic_view.get_model(target_id)
            if model is None:
                return None
            return TargetDescription(
                target_type=target_type,
                target_id=target_id,
                name=model.name,
                path=model.name,
                model_id=model.model_id,
            )
        if target_type == "semantic_entity":
            entity = await self._semantic_view.get_entity_by_id(target_id)
            if entity is None:
                return None
            model = await self._semantic_view.get_model(entity.model_id)
            model_name = model.name if model is not None else ""
            return TargetDescription(
                target_type=target_type,
                target_id=target_id,
                name=entity.name,
                path=f"{model_name} / {entity.name}",
                model_id=entity.model_id,
                entity_name=entity.name,
            )
        if target_type == "relationship":
            return await self._relationship_description(target_id)
        if target_type == "domain":
            domain = await self._vocabulary_view.get_domain(target_id)
            if domain is None:
                return None
            return TargetDescription(
                target_type=target_type,
                target_id=target_id,
                name=domain.name,
                path=domain.name,
                domain_id=domain.domain_id,
            )
        if target_type == "term":
            return await self._term_description(target_id)
        return None

    async def exists(self, target_type: str, target_id: UUID) -> bool:
        """Returns whether the target exists in its owning read model."""
        return await self._resolve(target_type, target_id) is not None

    async def _table_description(self, table: Any) -> TargetDescription:
        """Builds the description of a catalog table."""
        schema = await self._catalog_view.get_schema(table.schema_id)
        catalog = await self._catalog_view.get_catalog(table.catalog_id)
        schema_name = schema.name if schema is not None else ""
        catalog_name = catalog.name if catalog is not None else ""
        return TargetDescription(
            target_type="table",
            target_id=table.table_id,
            name=table.name,
            path=f"{catalog_name} / {schema_name} / {table.name}",
            catalog_id=table.catalog_id,
            schema_name=schema_name,
            table_name=table.name,
        )

    async def _relationship_description(self, relationship_id: UUID) -> TargetDescription | None:
        """Builds the description of a semantic relationship."""
        relationship = await self._semantic_view.get_relationship(relationship_id)
        if relationship is None:
            return None
        model = await self._semantic_view.get_model(relationship.model_id)
        model_name = model.name if model is not None else ""
        ends = " → ".join(ref[0] for ref in (relationship.from_refs[:1] + relationship.to_refs[:1]))
        return TargetDescription(
            target_type="relationship",
            target_id=relationship_id,
            name=ends or model_name,
            path=f"{model_name} / {ends}".strip(" /"),
            model_id=relationship.model_id,
        )

    async def _term_description(self, term_id: UUID) -> TargetDescription | None:
        """Builds the description of a vocabulary term."""
        term = await self._vocabulary_view.get_term(term_id)
        if term is None:
            return None
        domain = await self._vocabulary_view.get_domain(term.domain_id)
        domain_name = domain.name if domain is not None else ""
        return TargetDescription(
            target_type="term",
            target_id=term_id,
            name=term.name,
            path=f"{domain_name} / {term.path}",
            domain_id=term.domain_id,
        )

    async def tenant_of(self, target_type: str, target_id: UUID) -> UUID | None:
        """Returns the tenant that owns the target, or ``None``."""
        if target_type == "tenant":
            tenant = await self._iam_view.get_tenant(target_id)
            return None if tenant is None else tenant.tenant_id
        if target_type == "group":
            group = await self._iam_view.get_group(target_id)
            return None if group is None else group.tenant_id
        if target_type == "user":
            memberships = [
                membership
                for membership in await self._iam_view.list_memberships(target_id)
                if membership.status == "ACTIVE"
            ]
            if len(memberships) == 1:
                return memberships[0].tenant_id
            return None
        return None

    async def _resolve(self, target_type: str, target_id: UUID) -> Any:
        """Returns the row of the target, or ``None`` for an unknown type."""
        if target_type == "catalog":
            return await self._catalog_view.get_catalog(target_id)
        if target_type == "schema":
            return await self._catalog_view.get_schema(target_id)
        if target_type == "table":
            return await self._catalog_view.get_table(target_id)
        if target_type == "semantic_model":
            return await self._semantic_view.get_model(target_id)
        if target_type == "relationship":
            return await self._semantic_view.get_relationship(target_id)
        if target_type == "domain":
            return await self._vocabulary_view.get_domain(target_id)
        if target_type == "term":
            return await self._vocabulary_view.get_term(target_id)
        if target_type == "ingestion_connection":
            return await self._ingestion_view.get_connection(target_id)
        if target_type == "import_run":
            return await self._ingestion_view.get_import_run(target_id)
        if target_type == "tenant":
            return await self._iam_view.get_tenant(target_id)
        if target_type == "user":
            return await self._iam_view.get_user(target_id)
        if target_type == "group":
            return await self._iam_view.get_group(target_id)
        if target_type == "field":
            return await self._catalog_view.get_field(target_id)
        if target_type == "semantic_entity":
            return await self._semantic_view.get_entity_by_id(target_id)
        return None
