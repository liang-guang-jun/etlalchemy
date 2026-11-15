import { z } from 'zod';

import { client } from '@/shared/api/client';

/** One semantic model of the read model. */
export const modelSchema = z.object({
  model_id: z.string(),
  name: z.string(),
  description: z.string(),
});

export type Model = z.infer<typeof modelSchema>;

/** One business entity backed by a catalog table. */
export const entitySchema = z.object({
  model_id: z.string(),
  /** Identity of the entity, null on the response of a create call. */
  entity_id: z.string().nullish(),
  name: z.string(),
  table_id: z.string(),
});

export type Entity = z.infer<typeof entitySchema>;

/** One `entity.field` reference of a relationship side. */
export const fieldRefSchema = z.object({
  entity: z.string(),
  field: z.string(),
});

export type FieldRef = z.infer<typeof fieldRefSchema>;

/** Cardinalities the backend accepts. */
export const cardinalities = ['one_to_many', 'one_to_one', 'many_to_many'] as const;

export type Cardinality = (typeof cardinalities)[number];

/** Directions a relationship filter can flow in. */
export const filterDirections = ['single', 'both'] as const;

export type FilterDirection = (typeof filterDirections)[number];

/** A field-level relation between two entities of one model. */
export const relationshipSchema = z.object({
  relationship_id: z.string(),
  model_id: z.string(),
  from_refs: z.array(fieldRefSchema),
  to_refs: z.array(fieldRefSchema),
  cardinality: z.string(),
  filter_direction: z.string(),
  priority: z.number(),
});

export type Relationship = z.infer<typeof relationshipSchema>;

/** A canvas of one model. */
export const diagramSchema = z.object({
  model_id: z.string(),
  name: z.string(),
  order: z.number(),
});

export type Diagram = z.infer<typeof diagramSchema>;

/** One entity placed on a diagram canvas. */
export const diagramNodeSchema = z.object({
  model_id: z.string(),
  diagram_name: z.string(),
  entity_name: z.string(),
  x: z.number(),
  y: z.number(),
});

export type DiagramNode = z.infer<typeof diagramNodeSchema>;

/** Body of `POST /semantic/models`. */
export interface ModelCreate {
  name: string;
  description: string;
}

/** Body of `PATCH /semantic/models/{model_id}`. */
export interface ModelPatch {
  name?: string;
  description?: string;
}

/** Body of `PATCH .../entities/{entity_name}`. */
export interface EntityPatch {
  new_name?: string;
  table_id?: string;
}

/** Body of `POST .../relationships`. */
export interface RelationshipCreate {
  from_refs: FieldRef[];
  to_refs: FieldRef[];
  cardinality: Cardinality;
  filter_direction: FilterDirection;
  priority: number;
}

/** Body of `PATCH .../relationships/{relationship_id}`. */
export type RelationshipPatch = Partial<RelationshipCreate>;

/** Body of `POST .../diagrams`. */
export interface DiagramCreate {
  name: string;
  order: number;
}

/** Body of `PATCH .../diagrams/{name}`. */
export interface DiagramPatch {
  new_name?: string;
  order?: number;
}

/** Body of `POST .../diagrams/{name}/nodes`. */
export interface NodeCreate {
  entity_name: string;
  x: number;
  y: number;
}

/** Body of `PATCH .../diagrams/{name}/nodes/{entity_name}`. */
export interface NodePatch {
  x: number;
  y: number;
}

const modelCreatedSchema = z.object({ model_id: z.string() });
const relationshipCreatedSchema = z.object({ relationship_id: z.string() });

/**
 * Lists every live model.
 *
 * @returns The model rows, ordered by name.
 */
export async function fetchModels(): Promise<Model[]> {
  const response = await client.get('/semantic/models');
  return modelSchema.array().parse(response.data);
}

/**
 * Reads one model.
 *
 * @param modelId Id of the model.
 * @returns The model row.
 */
export async function fetchModel(modelId: string): Promise<Model> {
  const response = await client.get(`/semantic/models/${modelId}`);
  return modelSchema.parse(response.data);
}

/**
 * Creates a model.
 *
 * @param body Name and description of the new model.
 * @returns Id of the new model.
 */
export async function createModel(body: ModelCreate): Promise<string> {
  const response = await client.post('/semantic/models', body);
  return modelCreatedSchema.parse(response.data).model_id;
}

/**
 * Changes the name and/or description of a model.
 *
 * @param modelId Id of the model.
 * @param body Fields to change.
 */
export async function changeModel(modelId: string, body: ModelPatch): Promise<void> {
  await client.patch(`/semantic/models/${modelId}`, body);
}

/**
 * Discards a model with its entities, relationships and diagrams.
 *
 * @param modelId Id of the model.
 */
export async function discardModel(modelId: string): Promise<void> {
  await client.delete(`/semantic/models/${modelId}`);
}

/**
 * Lists the entities of a model.
 *
 * @param modelId Id of the model.
 * @returns The entity rows, ordered by name.
 */
export async function fetchEntities(modelId: string): Promise<Entity[]> {
  const response = await client.get(`/semantic/models/${modelId}/entities`);
  return entitySchema.array().parse(response.data);
}

/**
 * Adds an entity backed by a catalog table.
 *
 * @param modelId Id of the model.
 * @param body Name of the entity and the table it maps to.
 */
export async function addEntity(
  modelId: string,
  body: { name: string; table_id: string },
): Promise<void> {
  await client.post(`/semantic/models/${modelId}/entities`, body);
}

/**
 * Renames an entity and/or points it at another catalog table.
 *
 * @param modelId Id of the model.
 * @param entityName Current name of the entity.
 * @param body Fields to change.
 */
export async function changeEntity(
  modelId: string,
  entityName: string,
  body: EntityPatch,
): Promise<void> {
  await client.patch(
    `/semantic/models/${modelId}/entities/${encodeURIComponent(entityName)}`,
    body,
  );
}

/**
 * Removes an entity with the relationships and nodes that mention it.
 *
 * @param modelId Id of the model.
 * @param entityName Name of the entity.
 */
export async function removeEntity(modelId: string, entityName: string): Promise<void> {
  await client.delete(`/semantic/models/${modelId}/entities/${encodeURIComponent(entityName)}`);
}

/**
 * Lists the relationships of a model.
 *
 * @param modelId Id of the model.
 * @returns The relationship rows, ordered by priority and id.
 */
export async function fetchRelationships(modelId: string): Promise<Relationship[]> {
  const response = await client.get(`/semantic/models/${modelId}/relationships`);
  return relationshipSchema.array().parse(response.data);
}

/**
 * Adds a relationship between fields of two entities.
 *
 * @param modelId Id of the model.
 * @param body Paired references plus cardinality, direction and priority.
 * @returns Id of the new relationship.
 */
export async function addRelationship(modelId: string, body: RelationshipCreate): Promise<string> {
  const response = await client.post(`/semantic/models/${modelId}/relationships`, body);
  return relationshipCreatedSchema.parse(response.data).relationship_id;
}

/**
 * Changes the given attributes of a relationship.
 *
 * @param modelId Id of the model.
 * @param relationshipId Id of the relationship.
 * @param body Fields to change.
 */
export async function changeRelationship(
  modelId: string,
  relationshipId: string,
  body: RelationshipPatch,
): Promise<void> {
  await client.patch(`/semantic/models/${modelId}/relationships/${relationshipId}`, body);
}

/**
 * Removes a relationship.
 *
 * @param modelId Id of the model.
 * @param relationshipId Id of the relationship.
 */
export async function removeRelationship(modelId: string, relationshipId: string): Promise<void> {
  await client.delete(`/semantic/models/${modelId}/relationships/${relationshipId}`);
}

/**
 * Lists the diagrams of a model.
 *
 * @param modelId Id of the model.
 * @returns The diagram rows, ordered by order and name.
 */
export async function fetchDiagrams(modelId: string): Promise<Diagram[]> {
  const response = await client.get(`/semantic/models/${modelId}/diagrams`);
  return diagramSchema.array().parse(response.data);
}

/**
 * Adds an empty diagram to a model.
 *
 * @param modelId Id of the model.
 * @param body Name and sort hint of the new diagram.
 */
export async function addDiagram(modelId: string, body: DiagramCreate): Promise<void> {
  await client.post(`/semantic/models/${modelId}/diagrams`, body);
}

/**
 * Renames a diagram and/or changes its sort hint.
 *
 * @param modelId Id of the model.
 * @param name Current name of the diagram.
 * @param body Fields to change.
 */
export async function changeDiagram(
  modelId: string,
  name: string,
  body: DiagramPatch,
): Promise<void> {
  await client.patch(`/semantic/models/${modelId}/diagrams/${encodeURIComponent(name)}`, body);
}

/**
 * Removes a diagram with its nodes.
 *
 * @param modelId Id of the model.
 * @param name Name of the diagram.
 */
export async function removeDiagram(modelId: string, name: string): Promise<void> {
  await client.delete(`/semantic/models/${modelId}/diagrams/${encodeURIComponent(name)}`);
}

/**
 * Lists the nodes of a diagram.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @returns The placed nodes with their canvas coordinates.
 */
export async function fetchNodes(modelId: string, diagramName: string): Promise<DiagramNode[]> {
  const response = await client.get(
    `/semantic/models/${modelId}/diagrams/${encodeURIComponent(diagramName)}/nodes`,
  );
  return diagramNodeSchema.array().parse(response.data);
}

/**
 * Places an entity on a manual diagram.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @param body Entity to place and its coordinates.
 */
export async function placeNode(
  modelId: string,
  diagramName: string,
  body: NodeCreate,
): Promise<void> {
  await client.post(
    `/semantic/models/${modelId}/diagrams/${encodeURIComponent(diagramName)}/nodes`,
    body,
  );
}

/**
 * Moves a placed entity on a diagram.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @param entityName Name of the placed entity.
 * @param body New coordinates.
 */
export async function moveNode(
  modelId: string,
  diagramName: string,
  entityName: string,
  body: NodePatch,
): Promise<void> {
  await client.patch(
    `/semantic/models/${modelId}/diagrams/${encodeURIComponent(diagramName)}/nodes/${encodeURIComponent(entityName)}`,
    body,
  );
}

/**
 * Removes an entity from a manual diagram.
 *
 * @param modelId Id of the model.
 * @param diagramName Name of the diagram.
 * @param entityName Name of the placed entity.
 */
export async function removeNode(
  modelId: string,
  diagramName: string,
  entityName: string,
): Promise<void> {
  await client.delete(
    `/semantic/models/${modelId}/diagrams/${encodeURIComponent(diagramName)}/nodes/${encodeURIComponent(entityName)}`,
  );
}
