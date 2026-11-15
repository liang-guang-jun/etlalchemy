import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';

import { useModel } from '@/entities/semantic';
import {
  ALL_DIAGRAM,
  MODELS_PATH,
  modelPath,
  parseWorkspaceSearch,
  readLastDiagram,
  workspacePath,
  writeLastDiagram,
} from '@/shared/lib/semantic-routes';
import { Breadcrumbs } from '@/shared/ui';
import {
  DetailLevelSwitch,
  DiagramCanvas,
  readDetailLevel,
  writeDetailLevel,
  type EntityDetailLevel,
} from '@/widgets/semantic-canvas';

/**
 * Renders the model workspace canvas.
 *
 * The diagram and the selection live in the query string. This page keeps that
 * state canonical by filling in the diagram the browser opened last; the layout
 * above it rejects a model that no longer exists.
 *
 * @returns The canvas page.
 */
export default function SemanticWorkspacePage() {
  const { modelId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const state = parseWorkspaceSearch(searchParams.toString());
  const model = useModel(modelId);
  const [detailLevel, setDetailLevel] = useState<EntityDetailLevel>(readDetailLevel);

  useEffect(() => {
    writeDetailLevel(detailLevel);
  }, [detailLevel]);

  const diagramName = state.diagram ?? readLastDiagram(modelId) ?? ALL_DIAGRAM;
  const { diagram, entity, relationship } = state;

  useEffect(() => {
    if (diagram !== undefined) {
      return;
    }
    void navigate(workspacePath(modelId, { diagram: diagramName, entity, relationship }), {
      replace: true,
    });
  }, [diagram, diagramName, entity, relationship, modelId, navigate]);

  useEffect(() => {
    writeLastDiagram(modelId, diagramName);
  }, [modelId, diagramName]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-border-base px-3">
        <Breadcrumbs
          items={[
            { label: 'Models', to: MODELS_PATH },
            { label: model.data?.name ?? 'Model', to: modelPath(modelId) },
            { label: diagramName },
          ]}
        />
        <DetailLevelSwitch value={detailLevel} onChange={setDetailLevel} />
      </header>
      <div className="min-h-0 flex-1">
        <DiagramCanvas
          modelId={modelId}
          diagramName={diagramName}
          selectedEntity={entity}
          selectedRelationship={relationship}
          detailLevel={detailLevel}
        />
      </div>
    </div>
  );
}
