import { cn } from '@/shared/lib/cn';

export interface SwitchProps {
  /** Whether the switch is on. */
  checked: boolean;
  /** Called with the requested state when the user clicks it. */
  onCheckedChange: (checked: boolean) => void;
  /** Accessible name, also used as the tooltip. */
  label: string;
  /** Disables the control, keeping it visible. */
  disabled?: boolean;
  /** Extra classes of the track. */
  className?: string;
}

/**
 * Renders a compact on/off switch.
 *
 * A button with `role="switch"` keeps the control keyboard reachable and gives
 * screen readers the state, which a styled checkbox would hide behind its label.
 *
 * @param props Component props.
 * @returns The switch.
 */
export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled = false,
  className,
}: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={() => {
        onCheckedChange(!checked);
      }}
      className={cn(
        'relative inline-flex h-4 w-7 shrink-0 items-center rounded-full border transition-colors',
        checked ? 'border-brand bg-brand' : 'border-border-strong bg-bg-canvas',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          'block size-3 rounded-full bg-bg-surface shadow-sm transition-transform',
          checked ? 'translate-x-3.5' : 'translate-x-0.5',
        )}
      />
    </button>
  );
}
