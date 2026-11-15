import { DATA_TYPES, PARAMETERISED_DATA_TYPES } from '../api';

const PARAMETERISED: readonly string[] = PARAMETERISED_DATA_TYPES;

/** A parsed canonical data type. */
export interface ParsedDataType {
  base: string;
  args: number[];
}

/**
 * Parses `varchar(255)` style text into its base type and parameters.
 *
 * @param value Text entered by the user.
 * @returns The parsed type, or `null` when the text is not a canonical type.
 */
export function parseDataType(value: string): ParsedDataType | null {
  const trimmed = value.trim().toLowerCase();
  const match = /^([a-z]+)(?:\(([^)]*)\))?$/.exec(trimmed);
  if (match === null) {
    return null;
  }
  const base = match[1] ?? '';
  if (!(DATA_TYPES as readonly string[]).includes(base)) {
    return null;
  }
  const rawArgs = match[2];
  if (rawArgs === undefined) {
    return PARAMETERISED.includes(base) ? null : { base, args: [] };
  }
  if (!PARAMETERISED.includes(base)) {
    return null;
  }
  const args = rawArgs.split(',').map((part) => Number.parseInt(part.trim(), 10));
  if (args.some((argument) => Number.isNaN(argument) || argument <= 0)) {
    return null;
  }
  if (base === 'decimal' && args.length !== 2) {
    return null;
  }
  if ((base === 'varchar' || base === 'char') && args.length !== 1) {
    return null;
  }
  return { base, args };
}

/**
 * Renders a canonical data type back to text.
 *
 * @param base Canonical base type.
 * @param args Integer parameters.
 * @returns The canonical text form, e.g. `decimal(10,2)`.
 */
export function formatDataType(base: string, args: number[]): string {
  return args.length === 0 ? base : `${base}(${args.join(',')})`;
}

/**
 * Reports whether a base type requires parameters.
 *
 * @param base Canonical base type.
 * @returns `true` for `decimal`, `varchar` and `char`.
 */
export function isParameterised(base: string): boolean {
  return PARAMETERISED.includes(base);
}
