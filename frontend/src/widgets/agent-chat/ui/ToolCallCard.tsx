import { Bug, Check, ChevronRight, Clock, Loader2, ShieldX, Wrench } from 'lucide-react';

import type { AgentToolCall } from '@/entities/agent';
import { cn } from '@/shared/lib/cn';
import { Badge, type BadgeTone } from '@/shared/ui';

export interface ToolCallCardProps {
  /** Tool call to render. */
  call: AgentToolCall;
  /** Compact styling of the floating widget. */
  compact?: boolean;
  /** Called when the card is clicked; opens the detail drawer. */
  onOpen?: (call: AgentToolCall) => void;
}

/** Name of the generic resource tool, whose argument is the URI it read. */
const RESOURCE_TOOL = 'read_mcp_resource';

/**
 * Returns the URI a resource read addressed, when the call is one.
 *
 * @param call Tool call to inspect.
 * @returns The URI, or `null` for every other call.
 */
function resourceUri(call: AgentToolCall): string | null {
  if (call.tool !== RESOURCE_TOOL) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(call.argsJson);
    if (parsed === null || typeof parsed !== 'object' || !('uri' in parsed)) {
      return null;
    }
    const { uri } = parsed as { uri?: unknown };
    return typeof uri === 'string' ? uri : null;
  } catch {
    return null;
  }
}

const STATUS_TONE: Record<AgentToolCall['status'], BadgeTone> = {
  running: 'info',
  ok: 'success',
  error: 'danger',
  denied: 'warning',
};

const STATUS_LABEL: Record<AgentToolCall['status'], string> = {
  running: 'running',
  ok: 'ok',
  error: 'error',
  denied: 'denied',
};

/**
 * Picks the icon of a tool call status.
 *
 * @param status Status of the call.
 * @returns The icon element.
 */
function StatusIcon({ status }: { status: AgentToolCall['status'] }) {
  switch (status) {
    case 'running':
      return <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />;
    case 'ok':
      return <Check className="size-3.5" aria-hidden="true" />;
    case 'denied':
      return <ShieldX className="size-3.5" aria-hidden="true" />;
    default:
      return <Bug className="size-3.5" aria-hidden="true" />;
  }
}

/**
 * Renders the status of a tool call as a badge.
 *
 * @param props Status of the call.
 * @returns The badge with its icon.
 */
export function ToolStatusBadge({ status }: { status: AgentToolCall['status'] }) {
  return (
    <Badge tone={STATUS_TONE[status]}>
      <span className="inline-flex items-center gap-1">
        <StatusIcon status={status} />
        {STATUS_LABEL[status]}
      </span>
    </Badge>
  );
}

/**
 * Renders one MCP tool call of an assistant message.
 *
 * The card is a button when the caller can open the detail drawer; the arguments
 * themselves live there, not on the card, so a long payload never stretches the
 * transcript.
 *
 * @param props Component props.
 * @returns The tool card.
 */
export function ToolCallCard({ call, compact = false, onOpen }: ToolCallCardProps) {
  // A resource read is identified by the URI it read; every other call by its digest.
  const detail = resourceUri(call) ?? (call.argsHash === '' ? null : `args ${call.argsHash}`);
  const body = (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Wrench className="size-3.5 shrink-0 text-text-secondary" aria-hidden="true" />
        <code className="min-w-0 truncate font-mono text-xs text-text-primary">{call.tool}</code>
        <ToolStatusBadge status={call.status} />
        {call.durationMs === null ? null : (
          <span className="inline-flex items-center gap-1 text-[11px] text-text-secondary">
            <Clock className="size-3" aria-hidden="true" />
            {call.durationMs} ms
          </span>
        )}
        {call.errorCode === null ? null : (
          <span className="text-[11px] text-danger">{call.errorCode}</span>
        )}
        {onOpen === undefined ? null : (
          <ChevronRight
            className="ml-auto size-3.5 shrink-0 text-text-disabled"
            aria-hidden="true"
          />
        )}
      </div>
      {compact || detail === null ? null : (
        <p className="mt-1 truncate font-mono text-[11px] text-text-disabled">{detail}</p>
      )}
    </>
  );

  const shell = cn(
    'w-full rounded-md border border-border-base bg-bg-hover-subtle text-left',
    compact ? 'px-2 py-1' : 'px-2.5 py-1.5',
    onOpen === undefined ? null : 'transition-colors hover:border-border-strong',
  );

  if (onOpen === undefined) {
    return <div className={shell}>{body}</div>;
  }
  return (
    <button
      type="button"
      className={shell}
      aria-haspopup="dialog"
      aria-label={`Details of ${call.tool}`}
      onClick={() => {
        onOpen(call);
      }}
    >
      {body}
    </button>
  );
}
