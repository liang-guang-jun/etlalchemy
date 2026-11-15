import { Clock, FileJson } from 'lucide-react';

import type { AgentToolCall } from '@/entities/agent';
import { cn } from '@/shared/lib/cn';
import { prettyJson } from '@/shared/lib/json';
import { Drawer } from '@/shared/ui/drawer';

import { ToolStatusBadge } from './ToolCallCard';

export interface ToolCallDrawerProps {
  /** Call to inspect, or `null` while the drawer is closed. */
  call: AgentToolCall | null;
  /** Called by the overlay, the close button and Escape. */
  onClose: () => void;
}

/**
 * Renders the detail panel of one tool call.
 *
 * The arguments are redacted and the result is truncated by the server, so the
 * panel is a faithful summary rather than a recording of the payload.
 *
 * @param props Component props.
 * @returns The drawer, closed when no call is selected.
 */
export function ToolCallDrawer({ call, onClose }: ToolCallDrawerProps) {
  return (
    <Drawer
      open={call !== null}
      title={call === null ? 'Tool call' : <code className="font-mono text-sm">{call.tool}</code>}
      onClose={onClose}
      width="lg"
    >
      {call === null ? null : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <ToolStatusBadge status={call.status} />
            {call.durationMs === null ? null : (
              <span className="inline-flex items-center gap-1 text-xs text-text-secondary">
                <Clock className="size-3.5" aria-hidden="true" />
                {call.durationMs} ms
              </span>
            )}
            {call.errorCode === null ? null : (
              <span className="font-mono text-xs text-danger">{call.errorCode}</span>
            )}
          </div>

          <section>
            <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-text-secondary uppercase">
              Arguments
            </h3>
            {call.argsJson === '' ? (
              <p className="text-xs text-text-disabled">No arguments were recorded.</p>
            ) : (
              <pre className="max-h-[35vh] overflow-auto rounded-md border border-border-base bg-bg-canvas p-2.5 font-mono text-[11px] whitespace-pre-wrap text-text-primary">
                {prettyJson(call.argsJson)}
              </pre>
            )}
          </section>

          <section>
            <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-text-secondary uppercase">
              Result
            </h3>
            {call.resultPreview === '' ? (
              <p className="text-xs text-text-disabled">
                {call.status === 'running'
                  ? 'The tool is still running.'
                  : 'The tool returned no text.'}
              </p>
            ) : (
              <pre
                className={cn(
                  'max-h-[45vh] overflow-auto rounded-md border border-border-base bg-bg-canvas p-2.5 font-mono text-[11px] whitespace-pre-wrap',
                  call.status === 'error' || call.status === 'denied'
                    ? 'text-danger'
                    : 'text-text-primary',
                )}
              >
                {call.resultPreview}
              </pre>
            )}
          </section>

          {call.argsHash === '' ? null : (
            <p className="flex items-center gap-1.5 font-mono text-[10px] text-text-disabled">
              <FileJson className="size-3 shrink-0" aria-hidden="true" />
              args {call.argsHash}
            </p>
          )}
        </div>
      )}
    </Drawer>
  );
}
