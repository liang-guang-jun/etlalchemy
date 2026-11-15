import { useEffect } from 'react';
import { Cpu } from 'lucide-react';

import { useAgentProviders, useAgentStore, type AgentConversation } from '@/entities/agent';
import { DropdownMenu } from '@/shared/ui';

import { useSwitchProvider } from '../api/mutation';

export interface ProviderSwitcherProps {
  /** Conversation whose provider is switched, or `null` before one exists. */
  conversation: AgentConversation | null;
}

/**
 * Renders the model of the conversation and lets the user switch it.
 *
 * The selectable providers come from the LLM configuration context, so a user
 * only ever sees what they are allowed to use. Before the first message the
 * choice is kept in the shared store (and therefore persisted), so the
 * conversation is created with exactly that provider.
 *
 * @param props Component props.
 * @returns The switcher element.
 */
export function ProviderSwitcher({ conversation }: ProviderSwitcherProps) {
  const providers = useAgentProviders();
  const switchProvider = useSwitchProvider();
  const pendingProviderId = useAgentStore((state) => state.pendingProviderId);
  const setPendingProvider = useAgentStore((state) => state.setPendingProvider);
  const rows = providers.data ?? [];
  const selectedId = conversation?.active_llm_provider_id ?? pendingProviderId;
  const current = rows.find((provider) => provider.provider_id === selectedId);
  const pendingKnown =
    pendingProviderId === null ||
    rows.some((provider) => provider.provider_id === pendingProviderId);

  useEffect(() => {
    if (providers.isSuccess && !pendingKnown) {
      // The saved provider was discarded or unshared while the tab was closed.
      setPendingProvider(null);
    }
  }, [providers.isSuccess, pendingKnown, setPendingProvider]);

  const label = current?.name ?? (rows.length === 0 ? 'No provider' : 'Default provider');

  if (rows.length === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-border-base px-2 py-1 text-xs text-text-secondary">
        <Cpu className="size-3.5" aria-hidden="true" />
        {label}
      </span>
    );
  }

  if (conversation === null) {
    return (
      <DropdownMenu
        label={label}
        align="end"
        icon={<Cpu className="size-3.5 text-text-secondary" aria-hidden="true" />}
        items={[
          {
            label: pendingProviderId === null ? '✓ Default provider' : 'Default provider',
            onSelect: () => {
              setPendingProvider(null);
            },
          },
          ...rows.map((provider) => ({
            label:
              provider.provider_id === pendingProviderId ? `✓ ${provider.name}` : provider.name,
            onSelect: () => {
              setPendingProvider(provider.provider_id);
            },
          })),
        ]}
        triggerClassName="h-8 text-xs"
      />
    );
  }

  return (
    <DropdownMenu
      label={label}
      align="end"
      icon={<Cpu className="size-3.5 text-text-secondary" aria-hidden="true" />}
      items={rows.map((provider) => ({
        label:
          provider.provider_id === conversation.active_llm_provider_id
            ? `✓ ${provider.name}`
            : provider.name,
        disabled: switchProvider.isPending,
        onSelect: () => {
          switchProvider.mutate({
            conversation,
            providerId: provider.provider_id,
          });
        },
      }))}
      triggerClassName="h-8 text-xs"
    />
  );
}
