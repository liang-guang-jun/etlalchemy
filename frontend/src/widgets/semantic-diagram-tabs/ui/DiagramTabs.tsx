import { useMemo, useState } from 'react';
import { Lock, MoreHorizontal, Plus } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router';

import { useDiagrams, type Diagram } from '@/entities/semantic';
import {
  DiagramDialog,
  RemoveDiagramConfirm,
  useReorderDiagrams,
} from '@/features/semantic-diagram-actions';
import { cn } from '@/shared/lib/cn';
import { ALL_DIAGRAM, parseWorkspaceSearch, workspacePath } from '@/shared/lib/semantic-routes';
import { DropdownMenu, type DropdownMenuItem } from '@/shared/ui';

export interface DiagramTabsProps {
  modelId: string;
}

/**
 * Compares two diagrams: `All` first, then the sort hint, then the name.
 *
 * @param left Left diagram.
 * @param right Right diagram.
 * @returns The comparison result.
 */
function compareDiagrams(left: Diagram, right: Diagram): number {
  if (left.name === right.name) {
    return 0;
  }
  if (left.name === ALL_DIAGRAM) {
    return -1;
  }
  if (right.name === ALL_DIAGRAM) {
    return 1;
  }
  return left.order - right.order || left.name.localeCompare(right.name);
}

/**
 * Renders the diagram tabs of one model, in the style of spreadsheet sheet tabs.
 *
 * Tabs switch the diagram and can be dragged (or moved with Alt+Arrow) to change
 * their order; `All` is pinned first because the backend always shows every
 * entity on it. Renaming and deleting live in the per-tab menu.
 *
 * @param props Component props.
 * @returns The tab bar with its dialogs.
 */
export function DiagramTabs({ modelId }: DiagramTabsProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const state = parseWorkspaceSearch(searchParams.toString());
  const diagramName = state.diagram ?? ALL_DIAGRAM;
  const diagrams = useDiagrams(modelId);
  const reorder = useReorderDiagrams(modelId);
  const [dialog, setDialog] = useState<Diagram | 'new' | null>(null);
  const [removing, setRemoving] = useState<Diagram | null>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);

  const sorted = useMemo(() => [...(diagrams.data ?? [])].sort(compareDiagrams), [diagrams.data]);
  const manualNames = useMemo(
    () => sorted.filter((diagram) => diagram.name !== ALL_DIAGRAM).map((diagram) => diagram.name),
    [sorted],
  );
  const nextOrder = sorted.reduce((max, diagram) => Math.max(max, diagram.order), 0) + 1;

  /**
   * Sends only the sort hints that the drop actually changed.
   *
   * @param names Diagram names in their new display order.
   */
  const saveOrder = (names: string[]): void => {
    const changes = names
      .map((name, index) => ({ name, order: index + 1 }))
      .filter((change) => {
        const current = diagrams.data?.find((row) => row.name === change.name);
        return current !== undefined && current.order !== change.order;
      });
    if (changes.length > 0) {
      reorder.mutate(changes);
    }
  };

  /**
   * Moves one tab to the slot of another one.
   *
   * @param sourceName Name of the dragged diagram.
   * @param targetName Name of the diagram it was dropped on.
   */
  const moveTab = (sourceName: string, targetName: string): void => {
    const from = manualNames.indexOf(sourceName);
    const to = manualNames.indexOf(targetName);
    if (from < 0 || to < 0 || from === to) {
      return;
    }
    const next = [...manualNames];
    next.splice(from, 1);
    next.splice(to, 0, sourceName);
    saveOrder(next);
  };

  /**
   * Moves one tab by a relative offset, for the keyboard shortcut.
   *
   * @param name Name of the diagram.
   * @param delta Offset in tab positions.
   */
  const shiftTab = (name: string, delta: number): void => {
    const index = manualNames.indexOf(name);
    const target = manualNames[index + delta];
    if (target !== undefined) {
      moveTab(name, target);
    }
  };

  /**
   * Builds the action menu of one tab.
   *
   * @param diagram Diagram the tab belongs to.
   * @returns The menu items.
   */
  const menuItems = (diagram: Diagram): DropdownMenuItem[] => [
    {
      label: 'Rename',
      onSelect: () => {
        setDialog(diagram);
      },
    },
    {
      label: 'Delete',
      danger: true,
      onSelect: () => {
        setRemoving(diagram);
      },
    },
  ];

  return (
    <div className="flex h-9 shrink-0 items-stretch bg-bg-canvas">
      <div
        role="tablist"
        aria-label="Diagrams"
        className="flex min-w-0 flex-1 items-stretch overflow-x-auto"
      >
        {sorted.map((diagram) => {
          const active = diagram.name === diagramName;
          const manual = diagram.name !== ALL_DIAGRAM;
          return (
            <div
              key={diagram.name}
              draggable={manual}
              onDragStart={(event) => {
                setDragging(diagram.name);
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', diagram.name);
              }}
              onDragEnd={() => {
                setDragging(null);
                setDropTarget(null);
              }}
              onDragOver={(event) => {
                if (!manual || dragging === null || dragging === diagram.name) {
                  return;
                }
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
                setDropTarget(diagram.name);
              }}
              onDragLeave={() => {
                if (dropTarget === diagram.name) {
                  setDropTarget(null);
                }
              }}
              onDrop={(event) => {
                event.preventDefault();
                const source = dragging ?? event.dataTransfer.getData('text/plain');
                if (source !== '' && source !== diagram.name) {
                  moveTab(source, diagram.name);
                }
                setDragging(null);
                setDropTarget(null);
              }}
              className={cn(
                'group/tab relative flex shrink-0 items-stretch overflow-hidden border-r border-border-base transition-colors',
                // The active tab is a white label rising out of the grey strip:
                // no accent line under it, only the background and the top
                // corners separate it from the tabs around it.
                active
                  ? 'rounded-t-md bg-bg-surface'
                  : 'border-t border-border-base hover:bg-bg-hover',
                manual && 'cursor-grab active:cursor-grabbing',
                dragging === diagram.name && 'opacity-50',
                dropTarget === diagram.name && 'border-l-2 border-l-brand bg-brand/10',
              )}
            >
              <button
                type="button"
                role="tab"
                aria-selected={active}
                title={diagram.name}
                onClick={() => {
                  void navigate(workspacePath(modelId, { diagram: diagram.name }));
                }}
                onDoubleClick={() => {
                  if (manual) {
                    setDialog(diagram);
                  }
                }}
                onKeyDown={(event) => {
                  if (!manual || !event.altKey) {
                    return;
                  }
                  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                    event.preventDefault();
                    shiftTab(diagram.name, event.key === 'ArrowLeft' ? -1 : 1);
                  }
                }}
                className={cn(
                  'flex h-full min-w-0 items-center gap-1.5 pl-4 text-xs transition-colors',
                  manual ? 'pr-8' : 'pr-4',
                  active
                    ? 'font-medium text-text-primary'
                    : 'text-text-secondary hover:text-text-primary',
                )}
              >
                {manual ? null : (
                  <Lock className="size-3 shrink-0 text-text-disabled" aria-hidden="true" />
                )}
                <span className="max-w-40 truncate">{diagram.name}</span>
              </button>
              {manual ? (
                // Kept out of the flow so the label keeps its symmetric padding;
                // it only shows while the tab is hovered or selected.
                <span
                  className={cn(
                    'absolute top-1/2 right-1 -translate-y-1/2 transition-opacity',
                    active
                      ? 'opacity-100'
                      : 'opacity-0 group-hover/tab:opacity-100 group-focus-within/tab:opacity-100',
                  )}
                >
                  <DropdownMenu
                    iconOnly
                    align="start"
                    label={`Actions for ${diagram.name}`}
                    icon={<MoreHorizontal className="size-3.5" aria-hidden="true" />}
                    items={menuItems(diagram)}
                    triggerClassName="size-5 text-text-disabled hover:bg-bg-hover hover:text-text-primary"
                  />
                </span>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="flex shrink-0 items-center border-l border-border-base px-2">
        <button
          type="button"
          aria-label="New diagram"
          title="New diagram"
          onClick={() => {
            setDialog('new');
          }}
          className="flex size-6 items-center justify-center rounded-sm text-text-secondary transition-colors hover:bg-bg-hover hover:text-text-primary"
        >
          <Plus className="size-4" aria-hidden="true" />
        </button>
      </div>

      {dialog !== null ? (
        <DiagramDialog
          open
          modelId={modelId}
          diagram={dialog === 'new' ? undefined : dialog}
          nextOrder={nextOrder}
          onClose={() => {
            setDialog(null);
          }}
          onCreated={(name) => {
            void navigate(workspacePath(modelId, { diagram: name }));
          }}
        />
      ) : null}

      {removing !== null ? (
        <RemoveDiagramConfirm
          open
          modelId={modelId}
          diagramName={removing.name}
          onClose={() => {
            setRemoving(null);
          }}
          onRemoved={() => {
            if (removing.name === diagramName) {
              void navigate(workspacePath(modelId, { diagram: ALL_DIAGRAM }), { replace: true });
            }
          }}
        />
      ) : null}
    </div>
  );
}
