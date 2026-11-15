import { useEffect, useState } from 'react';

import { Input, Select } from '@/shared/ui';
import { DATA_TYPES } from '../api';
import { formatDataType, isParameterised, parseDataType } from '../lib/data-type';

export interface DataTypePickerProps {
  value: string;
  onChange: (value: string) => void;
  invalid?: boolean;
}

const DEFAULT_ARGS: Record<string, string> = {
  decimal: '10,2',
  varchar: '255',
  char: '10',
};

const OPTIONS = DATA_TYPES.map((type) => ({ value: type, label: type }));

/**
 * Edits a canonical data type, with an argument field for parameterised types.
 *
 * @param props Component props.
 * @returns The picker element.
 */
export function DataTypePicker({ value, onChange, invalid = false }: DataTypePickerProps) {
  const parsed = parseDataType(value);
  const [base, setBase] = useState(parsed?.base ?? 'string');
  const [args, setArgs] = useState(
    parsed !== null && parsed.args.length > 0 ? parsed.args.join(',') : '',
  );

  useEffect(() => {
    const next = parseDataType(value);
    if (next !== null) {
      setBase(next.base);
      setArgs(next.args.join(','));
    }
  }, [value]);

  const emit = (nextBase: string, nextArgs: string): void => {
    if (isParameterised(nextBase)) {
      const parsedArgs = nextArgs
        .split(',')
        .map((part) => Number.parseInt(part.trim(), 10))
        .filter((argument) => !Number.isNaN(argument));
      onChange(formatDataType(nextBase, parsedArgs));
      return;
    }
    onChange(nextBase);
  };

  return (
    <div className="flex items-start gap-2">
      <Select
        options={OPTIONS}
        value={base}
        invalid={invalid}
        onChange={(event) => {
          const nextBase = event.target.value;
          const nextArgs = isParameterised(nextBase) ? (DEFAULT_ARGS[nextBase] ?? '') : '';
          setBase(nextBase);
          setArgs(nextArgs);
          emit(nextBase, nextArgs);
        }}
      />
      {isParameterised(base) ? (
        <Input
          className="w-28"
          value={args}
          invalid={invalid}
          placeholder={DEFAULT_ARGS[base] ?? ''}
          onChange={(event) => {
            setArgs(event.target.value);
            emit(base, event.target.value);
          }}
        />
      ) : null}
      <span className="pt-2 text-xs text-text-muted">
        {parseDataType(value) === null ? 'Invalid type' : value}
      </span>
    </div>
  );
}
