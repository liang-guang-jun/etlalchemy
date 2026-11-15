import { parseTimestamp } from '@/shared/lib/timestamp';

import type { AgentMessage } from './transcript';

/**
 * Counts the collapsed steps of a message.
 *
 * @param message Message to inspect.
 * @returns The reasoning segments and the tool calls, in arrival order.
 */
export function stepCount(message: AgentMessage): number {
  return message.steps.length;
}

/**
 * Sums the wall-clock duration of the tool calls of a message.
 *
 * @param message Message to inspect.
 * @returns The total in milliseconds, `0` while no call finished.
 */
export function toolDurationMs(message: AgentMessage): number {
  return message.tools.reduce((total, call) => total + (call.durationMs ?? 0), 0);
}

/**
 * Measures the time the message spent thinking and calling tools.
 *
 * It runs from the first streamed event to the first answer token, so a long
 * tool call counts and the answer itself does not.
 *
 * @param message Message to inspect.
 * @returns The duration in milliseconds, or `null` when the timestamps are unknown.
 */
export function stepsDurationMs(message: AgentMessage): number | null {
  const started = parseTimestamp(message.streamStartedAt ?? '');
  const ended = parseTimestamp(message.answerStartedAt ?? message.completedAt ?? '');
  if (started === null || ended === null) {
    return null;
  }
  return Math.max(0, ended.getTime() - started.getTime());
}

/**
 * Formats a duration for the steps summary.
 *
 * @param milliseconds Duration to render.
 * @returns A compact value such as `840ms`, `1.4s`, `34s` or `1m 24s`.
 */
export function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) {
    return `${String(Math.round(milliseconds))}ms`;
  }
  const seconds = milliseconds / 1000;
  if (seconds < 10) {
    return `${seconds.toFixed(1)}s`;
  }
  if (seconds < 60) {
    return `${String(Math.round(seconds))}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest === 0 ? `${String(minutes)}m` : `${String(minutes)}m ${String(rest)}s`;
}

/**
 * Builds the summary of a folded trace: how many steps ran, how long they took.
 *
 * The tool time is the sum of the calls; the total also covers the model's
 * thinking before the first answer token, so the two are shown apart.
 *
 * @param message Message whose steps are summarised.
 * @returns The summary text.
 */
export function describeSteps(message: AgentMessage): string {
  const steps = stepCount(message);
  const parts = [
    steps === 1 ? 'Ran 1 step' : `Ran ${String(steps)} steps`,
    `tools ${formatDuration(toolDurationMs(message))}`,
  ];
  const total = stepsDurationMs(message);
  if (total !== null) {
    parts.push(`total ${formatDuration(total)}`);
  }
  return parts.join(' · ');
}
