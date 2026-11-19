"""HTTP routes exposing the semantic context."""

from __future__ import annotations

from uuid import UUID

from dependency_injector.wiring import Provide, inject
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.persistence import RecordConflictError
from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel

from etlalchemy.app.api.errors import install_exception_handlers
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.common import OkResponse
from etlalchemy.app.schemas.semantic import (
    DiagramResponse,
    EntityResponse,
    ModelCreatedResponse,
    ModelResponse,
    NodeResponse,
    RelationshipCreatedResponse,
    RelationshipResponse,
)
from etlalchemy.catalog.aggregates.errors import UnknownTableError
from etlalchemy.semantic.aggregates.errors import (
    SemanticError,
    UnknownDiagramError,
    UnknownEntityError,
    UnknownModelError,
    UnknownNodeError,
    UnknownRelationshipError,
)
from etlalchemy.semantic.aggregates.types import (
    Cardinality,
    FieldRef,
    FilterDirection,
)
from etlalchemy.semantic.application import ModelApplication
from etlalchemy.semantic.projection.view import (
    DiagramRow,
    EntityRow,
    ModelRow,
    RelationshipRow,
    SemanticView,
)

router = APIRouter(prefix="/semantic", tags=["semantic"])

CONFLICT_ERRORS = (SemanticError, RecordConflictError)
NOT_FOUND_ERRORS = (
    UnknownModelError,
    UnknownEntityError,
    UnknownRelationshipError,
    UnknownDiagramError,
    UnknownNodeError,
    UnknownTableError,
    AggregateNotFoundError,
)


def add_exception_handlers(app: FastAPI) -> None:
    """Maps semantic errors to HTTP responses."""
    install_exception_handlers(
        app,
        conflict=CONFLICT_ERRORS,
        not_found=NOT_FOUND_ERRORS,
        bad_request=(ValueError,),
    )


class ModelCreate(BaseModel):
    """Body of ``POST /semantic/models``."""

    name: str
    """Name of the new model."""
    description: str = ""
    """Free-form description of the new model."""


class ModelPatch(BaseModel):
    """Body of ``PATCH /semantic/models/{model_id}``."""

    name: str | None = None
    """New name, or ``None`` to keep the current one."""
    description: str | None = None
    """New description, or ``None`` to keep the current one."""


class EntityCreate(BaseModel):
    """Body of ``POST /semantic/models/{model_id}/entities``."""

    name: str
    """Name of the new entity."""
    table_id: UUID
    """ID of the catalog table the entity maps to."""


class EntityPatch(BaseModel):
    """Body of ``PATCH .../entities/{entity_name}``.

    The rename is applied first, so a ``table_id`` in the same body applies to the
    renamed entity.
    """

    new_name: str | None = None
    """New name, or ``None`` to keep the current one."""
    table_id: UUID | None = None
    """New catalog table, or ``None`` to keep the current one."""


class FieldRefBody(BaseModel):
    """One ``entity.field`` reference in a relationship body."""

    entity: str
    """Name of the entity that owns the field."""
    field: str
    """Name of the field."""

    def to_ref(self) -> FieldRef:
        """Returns the value object the application expects."""
        return FieldRef(entity=self.entity, field=self.field)


class RelationshipCreate(BaseModel):
    """Body of ``POST .../relationships``.

    ``from_refs`` and ``to_refs`` pair up item by item, so they must have the
    same length.
    """

    from_refs: list[FieldRefBody]
    """``from`` references."""
    to_refs: list[FieldRefBody]
    """``to`` references, paired with ``from_refs`` by position."""
    cardinality: Cardinality
    """Cardinality of the relation."""
    filter_direction: FilterDirection = FilterDirection.SINGLE
    """Direction in which a filter flows across the relation."""
    priority: int = 0
    """Sort hint, lower first."""


class RelationshipPatch(BaseModel):
    """Body of ``PATCH .../relationships/{relationship_id}``."""

    from_refs: list[FieldRefBody] | None = None
    """New ``from`` references, or ``None`` to keep the current ones."""
    to_refs: list[FieldRefBody] | None = None
    """New ``to`` references, or ``None`` to keep the current ones."""
    cardinality: Cardinality | None = None
    """New cardinality, or ``None`` to keep the current one."""
    filter_direction: FilterDirection | None = None
    """New filter direction, or ``None`` to keep the current one."""
    priority: int | None = None
    """New sort hint, or ``None`` to keep the current one."""


class DiagramCreate(BaseModel):
    """Body of ``POST .../diagrams``."""

    name: str
    """Name of the new diagram."""
    order: int = 0
    """Sort hint, lower first."""


class DiagramPatch(BaseModel):
    """Body of ``PATCH .../diagrams/{name}``.

    The rename is applied first, so an ``order`` in the same body applies to the
    renamed diagram.
    """

    new_name: str | None = None
    """New name, or ``None`` to keep the current one."""
    order: int | None = None
    """New sort hint, or ``None`` to keep the current one."""


class NodeCreate(BaseModel):
    """Body of ``POST .../diagrams/{name}/nodes``."""

    entity_name: str
    """Name of the entity to place."""
    x: float = 0.0
    """Horizontal position on the canvas."""
    y: float = 0.0
    """Vertical position on the canvas."""


class NodePatch(BaseModel):
    """Body of ``PATCH .../diagrams/{name}/nodes/{entity_name}``."""

    x: float
    """New horizontal position."""
    y: float
    """New vertical position."""


async def _model_row(view: SemanticView, model_id: UUID) -> ModelRow:
    """Returns a live model, rejecting an unknown or discarded id."""
    row = await view.get_model(model_id)
    if row is None:
        msg = f"Model {model_id} not found"
        raise UnknownModelError(msg)
    return row


async def _entity_row(view: SemanticView, model_id: UUID, entity_name: str) -> EntityRow:
    """Returns an entity of the model, rejecting an unknown name."""
    await _model_row(view, model_id)
    row = await view.get_entity(model_id, entity_name)
    if row is None:
        msg = f"Entity {entity_name!r} does not exist in model {model_id}"
        raise UnknownEntityError(msg)
    return row


async def _diagram_row(view: SemanticView, model_id: UUID, name: str) -> DiagramRow:
    """Returns a diagram of the model, rejecting an unknown name."""
    await _model_row(view, model_id)
    row = await view.get_diagram(model_id, name)
    if row is None:
        msg = f"Diagram {name!r} does not exist in model {model_id}"
        raise UnknownDiagramError(msg)
    return row


async def _relationship_row(
    view: SemanticView,
    model_id: UUID,
    relationship_id: UUID,
) -> RelationshipRow:
    """Returns a relationship, rejecting an id owned by another model."""
    await _model_row(view, model_id)
    row = await view.get_relationship(relationship_id)
    if row is None or row.model_id != model_id:
        msg = f"Relationship {relationship_id} does not exist in model {model_id}"
        raise UnknownRelationshipError(msg)
    return row


# -- model ------------------------------------------------------------------


@router.post("/models", status_code=201, response_model=ModelCreatedResponse)
@inject
async def create_model(
    body: ModelCreate,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> ModelCreatedResponse:
    """Creates a semantic model and returns its ID."""
    model_id = await application.create_model(body.name, body.description)
    return ModelCreatedResponse(model_id=model_id)


@router.get("/models", response_model=list[ModelResponse])
@inject
async def list_models(
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> list[ModelResponse]:
    """Lists all live models from the read model."""
    return [ModelResponse.from_row(row) for row in await view.list_models()]


@router.get("/models/{model_id}", response_model=ModelResponse)
@inject
async def get_model(
    model_id: UUID,
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> ModelResponse:
    """Returns one live model."""
    return ModelResponse.from_row(await _model_row(view, model_id))


@router.patch("/models/{model_id}", response_model=OkResponse)
@inject
async def change_model(
    model_id: UUID,
    body: ModelPatch,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> OkResponse:
    """Changes the name and/or description of a model."""
    await application.change_model(model_id, body.name, body.description)
    return OkResponse()


@router.delete("/models/{model_id}", status_code=204)
@inject
async def discard_model(
    model_id: UUID,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> None:
    """Discards a model with everything it owned."""
    await application.discard_model(model_id)


# -- entities ---------------------------------------------------------------


@router.post(
    "/models/{model_id}/entities",
    status_code=201,
    response_model=EntityResponse,
)
@inject
async def add_entity(
    model_id: UUID,
    body: EntityCreate,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> EntityResponse:
    """Adds an entity backed by a catalog table."""
    entity_id = await application.add_entity(model_id, body.name, body.table_id)
    return EntityResponse(
        model_id=model_id,
        entity_id=entity_id,
        name=body.name,
        table_id=body.table_id,
    )


@router.get("/models/{model_id}/entities", response_model=list[EntityResponse])
@inject
async def list_entities(
    model_id: UUID,
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> list[EntityResponse]:
    """Lists the entities of a model."""
    await _model_row(view, model_id)
    return [EntityResponse.from_row(row) for row in await view.list_entities(model_id)]


@router.get("/models/{model_id}/entities/{entity_name}", response_model=EntityResponse)
@inject
async def get_entity(
    model_id: UUID,
    entity_name: str,
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> EntityResponse:
    """Returns one entity of a model."""
    return EntityResponse.from_row(await _entity_row(view, model_id, entity_name))


@router.patch("/models/{model_id}/entities/{entity_name}", response_model=OkResponse)
@inject
async def change_entity(
    model_id: UUID,
    entity_name: str,
    body: EntityPatch,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> OkResponse:
    """Renames an entity and/or points it at another catalog table."""
    if body.new_name is None and body.table_id is None:
        raise ValueError("PATCH requires new_name or table_id")
    current = entity_name
    if body.new_name is not None:
        await application.rename_entity(model_id, entity_name, body.new_name)
        current = body.new_name
    if body.table_id is not None:
        await application.change_entity_table(model_id, current, body.table_id)
    return OkResponse()


@router.delete("/models/{model_id}/entities/{entity_name}", status_code=204)
@inject
async def remove_entity(
    model_id: UUID,
    entity_name: str,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> None:
    """Removes an entity with its relationships and diagram nodes."""
    await application.remove_entity(model_id, entity_name)


# -- relationships ----------------------------------------------------------


@router.post(
    "/models/{model_id}/relationships",
    status_code=201,
    response_model=RelationshipCreatedResponse,
)
@inject
async def add_relationship(
    model_id: UUID,
    body: RelationshipCreate,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> RelationshipCreatedResponse:
    """Adds a relationship between fields of two entities."""
    relationship_id = await application.add_relationship(
        model_id,
        [ref.to_ref() for ref in body.from_refs],
        [ref.to_ref() for ref in body.to_refs],
        body.cardinality,
        body.filter_direction,
        body.priority,
    )
    return RelationshipCreatedResponse(relationship_id=relationship_id)


@router.get(
    "/models/{model_id}/relationships",
    response_model=list[RelationshipResponse],
)
@inject
async def list_relationships(
    model_id: UUID,
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> list[RelationshipResponse]:
    """Lists the relationships of a model."""
    await _model_row(view, model_id)
    return [RelationshipResponse.from_row(row) for row in await view.list_relationships(model_id)]


@router.get(
    "/models/{model_id}/relationships/{relationship_id}",
    response_model=RelationshipResponse,
)
@inject
async def get_relationship(
    model_id: UUID,
    relationship_id: UUID,
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> RelationshipResponse:
    """Returns one relationship of a model."""
    return RelationshipResponse.from_row(await _relationship_row(view, model_id, relationship_id))


@router.patch(
    "/models/{model_id}/relationships/{relationship_id}",
    response_model=OkResponse,
)
@inject
async def change_relationship(
    model_id: UUID,
    relationship_id: UUID,
    body: RelationshipPatch,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> OkResponse:
    """Changes the given attributes of a relationship."""
    await application.change_relationship(
        model_id,
        relationship_id,
        None if body.from_refs is None else [ref.to_ref() for ref in body.from_refs],
        None if body.to_refs is None else [ref.to_ref() for ref in body.to_refs],
        body.cardinality,
        body.filter_direction,
        body.priority,
    )
    return OkResponse()


@router.delete(
    "/models/{model_id}/relationships/{relationship_id}",
    status_code=204,
)
@inject
async def remove_relationship(
    model_id: UUID,
    relationship_id: UUID,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> None:
    """Removes a relationship."""
    await application.remove_relationship(model_id, relationship_id)


# -- diagrams ---------------------------------------------------------------


@router.post("/models/{model_id}/diagrams", status_code=201, response_model=DiagramResponse)
@inject
async def add_diagram(
    model_id: UUID,
    body: DiagramCreate,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> DiagramResponse:
    """Adds an empty diagram to a model."""
    await application.add_diagram(model_id, body.name, body.order)
    return DiagramResponse(model_id=model_id, name=body.name, order=body.order)


@router.get("/models/{model_id}/diagrams", response_model=list[DiagramResponse])
@inject
async def list_diagrams(
    model_id: UUID,
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> list[DiagramResponse]:
    """Lists the diagrams of a model."""
    await _model_row(view, model_id)
    return [DiagramResponse.from_row(row) for row in await view.list_diagrams(model_id)]


@router.get("/models/{model_id}/diagrams/{name}", response_model=DiagramResponse)
@inject
async def get_diagram(
    model_id: UUID,
    name: str,
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> DiagramResponse:
    """Returns one diagram of a model."""
    return DiagramResponse.from_row(await _diagram_row(view, model_id, name))


@router.patch("/models/{model_id}/diagrams/{name}", response_model=OkResponse)
@inject
async def change_diagram(
    model_id: UUID,
    name: str,
    body: DiagramPatch,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> OkResponse:
    """Renames a diagram and/or changes its sort hint."""
    if body.new_name is None and body.order is None:
        raise ValueError("PATCH requires new_name or order")
    current = name
    if body.new_name is not None:
        await application.rename_diagram(model_id, name, body.new_name)
        current = body.new_name
    if body.order is not None:
        await application.change_diagram_order(model_id, current, body.order)
    return OkResponse()


@router.delete("/models/{model_id}/diagrams/{name}", status_code=204)
@inject
async def remove_diagram(
    model_id: UUID,
    name: str,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> None:
    """Removes a diagram with its nodes."""
    await application.remove_diagram(model_id, name)


# -- nodes ------------------------------------------------------------------


@router.post(
    "/models/{model_id}/diagrams/{name}/nodes",
    status_code=201,
    response_model=NodeResponse,
)
@inject
async def place_node(
    model_id: UUID,
    name: str,
    body: NodeCreate,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> NodeResponse:
    """Places an entity on a diagram."""
    await application.place_node(model_id, name, body.entity_name, body.x, body.y)
    return NodeResponse(
        model_id=model_id,
        diagram_name=name,
        entity_name=body.entity_name,
        x=body.x,
        y=body.y,
    )


@router.get(
    "/models/{model_id}/diagrams/{name}/nodes",
    response_model=list[NodeResponse],
)
@inject
async def list_nodes(
    model_id: UUID,
    name: str,
    view: SemanticView = Depends(Provide[Container.semantic_view]),  # noqa: B008
) -> list[NodeResponse]:
    """Lists the nodes of a diagram."""
    await _diagram_row(view, model_id, name)
    return [NodeResponse.from_row(row) for row in await view.list_nodes(model_id, name)]


@router.patch(
    "/models/{model_id}/diagrams/{name}/nodes/{entity_name}",
    response_model=OkResponse,
)
@inject
async def move_node(
    model_id: UUID,
    name: str,
    entity_name: str,
    body: NodePatch,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> OkResponse:
    """Moves a placed entity on a diagram."""
    await application.move_node(model_id, name, entity_name, body.x, body.y)
    return OkResponse()


@router.delete(
    "/models/{model_id}/diagrams/{name}/nodes/{entity_name}",
    status_code=204,
)
@inject
async def remove_node(
    model_id: UUID,
    name: str,
    entity_name: str,
    application: ModelApplication = Depends(  # noqa: B008
        Provide[Container.semantic_application]
    ),
) -> None:
    """Removes an entity from a diagram."""
    await application.remove_node(model_id, name, entity_name)
