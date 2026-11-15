"""Catalog read model: the materialised view and the projection that fills it."""

from etlalchemy.catalog.projection.projection import CatalogProjection, run_catalog_projection
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from etlalchemy.catalog.projection.view import (
    CatalogRow,
    CatalogView,
    FieldRow,
    FieldSearchResult,
    SchemaRow,
    TableRow,
)

__all__ = [
    "CatalogProjection",
    "CatalogRow",
    "CatalogView",
    "FieldRow",
    "FieldSearchResult",
    "SQLAlchemyCatalogView",
    "SchemaRow",
    "TableRow",
    "run_catalog_projection",
]
