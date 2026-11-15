import { Navigate, useOutlet, useParams } from 'react-router';

import { useModel } from '@/entities/semantic';
import { isApiError } from '@/shared/api/error';
import { MODELS_PATH, clearLastDiagram } from '@/shared/lib/semantic-routes';
import { ErrorState, Skeleton } from '@/shared/ui';
import { DiagramTabs } from '@/widgets/semantic-diagram-tabs';
import { SemanticExplorer } from '@/widgets/semantic-explorer';

/**
 * Layout of one semantic model workspace: the explorer on the left, the canvas
 * on the right and the diagram tabs across the bottom.
 *
 * The tab bar spans the whole width, including the explorer column, so it reads
 * like the sheet tabs of a spreadsheet.
 *
 * The model is read before the panels mount: a discarded model would otherwise
 * fire one failed request per panel before the redirect could happen.
 *
 * @returns The workspace layout.
 */
export function SemanticWorkspaceLayout() {
  const { modelId = '' } = useParams();
  const outlet = useOutlet();
  const model = useModel(modelId);

  if (model.isError) {
    if (isApiError(model.error) && model.error.kind === 'not_found') {
      clearLastDiagram(modelId);
      return <Navigate to={MODELS_PATH} replace />;
    }
    return (
      <div className="p-8">
        <ErrorState
          detail={model.error instanceof Error ? model.error.message : undefined}
          onRetry={() => {
            void model.refetch();
          }}
        />
      </div>
    );
  }

  if (model.isPending) {
    return (
      <div className="p-8">
        <Skeleton lines={6} />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-72 shrink-0 flex-col border-r border-border-base bg-bg-surface">
          <SemanticExplorer modelId={modelId} />
        </aside>

        <div className="min-w-0 flex-1 overflow-hidden bg-bg-surface">{outlet}</div>
      </div>

      <DiagramTabs modelId={modelId} />
    </div>
  );
}
