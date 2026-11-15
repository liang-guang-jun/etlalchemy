import { useMemo, useState } from 'react';
import { MoreHorizontal, Network, Plus } from 'lucide-react';
import { motion } from 'motion/react';
import { Link } from 'react-router';

import { useModels, type Model } from '@/entities/semantic';
import {
  CreateModelDialog,
  DiscardModelConfirm,
  EditModelDialog,
} from '@/features/semantic-model-actions';
import { modelPath } from '@/shared/lib/semantic-routes';
import {
  Button,
  DropdownMenu,
  EmptyState,
  ErrorState,
  PageHeader,
  SearchInput,
  Skeleton,
  type DropdownMenuItem,
} from '@/shared/ui';

/**
 * Renders the semantic model gallery: one card per model, a keyword filter and
 * the per-card rename / delete actions.
 *
 * @returns The model gallery page.
 */
export default function SemanticListPage() {
  const models = useModels();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Model | null>(null);
  const [discarding, setDiscarding] = useState<Model | null>(null);
  const [term, setTerm] = useState('');

  const rows = useMemo(() => models.data ?? [], [models.data]);

  const filtered = useMemo(() => {
    const needle = term.trim().toLowerCase();
    if (needle === '') {
      return rows;
    }
    return rows.filter((model) =>
      [model.name, model.description].some((value) => value.toLowerCase().includes(needle)),
    );
  }, [rows, term]);

  /**
   * Builds the action menu of one model card.
   *
   * @param model Model the menu belongs to.
   * @returns The menu items.
   */
  const menuItems = (model: Model): DropdownMenuItem[] => [
    {
      label: 'Edit model',
      onSelect: () => {
        setEditing(model);
      },
    },
    {
      label: 'Delete model',
      danger: true,
      onSelect: () => {
        setDiscarding(model);
      },
    },
  ];

  const newModelButton = (
    <Button
      icon={<Plus className="size-4" />}
      onClick={() => {
        setCreating(true);
      }}
    >
      New model
    </Button>
  );

  return (
    <div>
      <PageHeader
        title="Semantic models"
        description="Group the entities and relationships of a business area, then lay them out on diagrams."
        actions={
          rows.length === 0 ? (
            newModelButton
          ) : (
            <>
              <SearchInput
                ariaLabel="Search models"
                placeholder="Search models…"
                value={term}
                onChange={setTerm}
              />
              {newModelButton}
            </>
          )
        }
      />

      {models.isPending ? (
        <Skeleton lines={6} />
      ) : models.isError ? (
        <ErrorState
          detail={models.error instanceof Error ? models.error.message : undefined}
          onRetry={() => {
            void models.refetch();
          }}
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Network className="size-10" aria-hidden="true" />}
          title="No semantic model yet"
          description="A model maps catalog tables onto the business entities your users recognise."
          action={newModelButton}
          className="py-20"
        />
      ) : filtered.length === 0 ? (
        <EmptyState plain title="No model matches" description={`Nothing matches “${term}”.`} />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((model) => (
            <motion.li
              key={model.model_id}
              layout
              whileHover={{ y: -2 }}
              transition={{ type: 'spring', stiffness: 420, damping: 28 }}
              className="group relative flex flex-col gap-2 rounded-lg border border-border-base bg-bg-surface p-4 transition-colors hover:border-border-strong"
            >
              <Link
                to={modelPath(model.model_id)}
                aria-label={`Open ${model.name}`}
                className="absolute inset-0 rounded-lg"
              />
              <div className="flex items-center gap-2">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-brand/15 text-text-primary">
                  <Network className="size-4" aria-hidden="true" />
                </span>
                <span className="truncate font-semibold text-text-primary">{model.name}</span>
                <span className="relative z-10 ml-auto opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  <DropdownMenu
                    iconOnly
                    align="end"
                    label={`Actions for ${model.name}`}
                    icon={<MoreHorizontal className="size-3.5" aria-hidden="true" />}
                    items={menuItems(model)}
                    triggerClassName="size-6 text-text-disabled hover:bg-bg-hover hover:text-text-primary"
                  />
                </span>
              </div>
              <p className="line-clamp-3 min-h-10 text-sm text-text-secondary">
                {model.description === '' ? 'No description yet.' : model.description}
              </p>
            </motion.li>
          ))}
        </ul>
      )}

      <CreateModelDialog
        open={creating}
        onClose={() => {
          setCreating(false);
        }}
      />

      {editing !== null ? (
        <EditModelDialog
          open
          model={editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}

      {discarding !== null ? (
        <DiscardModelConfirm
          open
          model={discarding}
          onClose={() => {
            setDiscarding(null);
          }}
        />
      ) : null}
    </div>
  );
}
