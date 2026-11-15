import { useState } from 'react';
import { ShieldAlert } from 'lucide-react';

import type { AgentApproval } from '@/entities/agent';
import { cn } from '@/shared/lib/cn';
import { Badge, Button } from '@/shared/ui';

import { useAgentChat } from '../model/use-agent-chat';

export interface ApprovalCardProps {
  /** Conversation the run belongs to. */
  conversationId: string;
  /** Approval to render. */
  approval: AgentApproval;
  /**
   * Compact form for the floating widget: tool name and the two buttons only.
   * The full form adds the digest and the policy reason.
   */
  compact?: boolean;
}

const STATUS_TONE = {
  pending: 'warning',
  approved: 'success',
  denied: 'danger',
} as const;

/**
 * Renders a human-in-the-loop decision.
 *
 * The arguments themselves never leave the server — only their digest does — so
 * the full form shows the tool, the digest and the reason instead of pretending
 * to know the payload.
 *
 * @param props Component props.
 * @returns The approval card.
 */
export function ApprovalCard({ conversationId, approval, compact = false }: ApprovalCardProps) {
  const { decide, running } = useAgentChat(conversationId);
  const [deciding, setDeciding] = useState(false);
  const pending = approval.status === 'pending';

  const answer = (approved: boolean) => {
    setDeciding(true);
    void decide(approval.approvalId, approved).finally(() => {
      setDeciding(false);
    });
  };

  return (
    <div
      className={cn(
        'rounded-lg border border-warning/40 bg-warning/10 p-3',
        compact ? 'text-xs' : 'text-sm',
      )}
      role="group"
      aria-label={`Approval for ${approval.tool}`}
    >
      <div className="flex items-start gap-2">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warning-ink" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-text-primary">Approval required</span>
            <Badge tone={STATUS_TONE[approval.status]}>{approval.status}</Badge>
          </div>
          <p className="mt-1 break-words text-text-primary">
            <code className="rounded-sm bg-bg-surface/70 px-1 py-0.5 font-mono text-[0.9em]">
              {approval.tool}
            </code>
          </p>
          {compact ? null : (
            <>
              {approval.reason === '' ? null : (
                <p className="mt-1 text-text-secondary">{approval.reason}</p>
              )}
              <p className="mt-2 text-[11px] text-text-secondary">
                Arguments digest{' '}
                <code className="break-all font-mono text-text-primary">
                  {approval.argsHash === '' ? '—' : approval.argsHash}
                </code>
              </p>
              <p className="mt-1 text-[11px] text-text-secondary">
                The arguments stay on the server; only their digest is shown here.
              </p>
            </>
          )}

          {pending ? (
            <div className="mt-2.5 flex gap-2">
              <Button
                size="sm"
                loading={deciding}
                disabled={!running || deciding}
                onClick={() => {
                  answer(true);
                }}
              >
                Approve
              </Button>
              <Button
                size="sm"
                variant="danger-ghost"
                disabled={!running || deciding}
                onClick={() => {
                  answer(false);
                }}
              >
                Deny
              </Button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
