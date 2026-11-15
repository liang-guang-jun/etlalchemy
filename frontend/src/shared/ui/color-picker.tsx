import { useEffect, useState } from 'react';
import { Ban, Pipette } from 'lucide-react';

import { cn } from '@/shared/lib/cn';

/** Colours offered by the picker; they follow the workspace palette. */
const SWATCH_COLORS = [
  '#f2c811',
  '#ffd335',
  '#6bb700',
  '#038387',
  '#0078d4',
  '#8764b8',
  '#e3008c',
  '#d13438',
  '#8a8886',
] as const;

const HEX_PATTERN = /^#?[0-9a-fA-F]{0,6}$/;

export interface ColorPickerProps {
  /** Selected colour as `#rrggbb`, or an empty string for none. */
  value: string;
  /** Called with the new `#rrggbb` value, or an empty string to clear it. */
  onChange: (value: string) => void;
  /** Renders the control as read-only. */
  disabled?: boolean;
  /** Accessible group label. */
  label?: string;
}

/**
 * Renders a swatch grid with a free hex input and a native colour dialog.
 *
 * @param props Component props.
 * @returns The colour picker.
 */
export function ColorPicker({
  value,
  onChange,
  disabled = false,
  label = 'Colour',
}: ColorPickerProps) {
  const [draft, setDraft] = useState(value);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  const commit = (next: string) => {
    if (!HEX_PATTERN.test(next)) {
      return;
    }
    const digits = next.replace('#', '').toLowerCase();
    setDraft(`#${digits}`);
    if (digits === '') {
      onChange('');
      return;
    }
    if (digits.length === 6) {
      onChange(`#${digits}`);
    }
  };

  return (
    <div className="space-y-2" role="group" aria-label={label}>
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          aria-label="No colour"
          aria-pressed={value === ''}
          disabled={disabled}
          onClick={() => {
            onChange('');
          }}
          className={cn(
            'flex size-6 items-center justify-center rounded-sm border border-border-strong bg-bg-surface text-text-disabled transition-shadow hover:text-text-primary disabled:cursor-not-allowed',
            value === '' && 'ring-2 ring-brand ring-offset-1 ring-offset-bg-surface',
          )}
        >
          <Ban className="size-3.5" aria-hidden="true" />
        </button>
        {SWATCH_COLORS.map((color) => (
          <button
            key={color}
            type="button"
            aria-label={`Use ${color}`}
            aria-pressed={value === color}
            disabled={disabled}
            onClick={() => {
              onChange(color);
            }}
            style={{ backgroundColor: color }}
            className={cn(
              'size-6 rounded-sm border border-black/10 transition-shadow disabled:cursor-not-allowed',
              value === color && 'ring-2 ring-brand ring-offset-1 ring-offset-bg-surface',
            )}
          />
        ))}
        <label
          className={cn(
            'relative flex size-6 cursor-pointer items-center justify-center rounded-sm border border-border-strong bg-bg-surface text-text-secondary hover:text-text-primary',
            disabled && 'pointer-events-none opacity-50',
          )}
          title="Custom colour"
        >
          <Pipette className="size-3.5" aria-hidden="true" />
          <input
            type="color"
            aria-label="Custom colour"
            value={value === '' ? '#f2c811' : value}
            disabled={disabled}
            onChange={(event) => {
              onChange(event.target.value.toLowerCase());
            }}
            className="absolute inset-0 cursor-pointer opacity-0"
          />
        </label>
        <input
          aria-label="Colour hex value"
          value={draft}
          disabled={disabled}
          spellCheck={false}
          onChange={(event) => {
            commit(event.target.value);
          }}
          onBlur={() => {
            setDraft(value);
          }}
          className="h-7 w-24 rounded-sm border border-border-base bg-bg-surface px-2 font-mono text-xs text-text-primary outline-none transition-colors placeholder:text-text-disabled focus:border-brand disabled:cursor-not-allowed disabled:bg-bg-canvas"
          placeholder="#rrggbb"
        />
      </div>
    </div>
  );
}
