/** A value that may be absent. */
export type Nullable<T> = T | null;

/** Option rendered by a select or a combobox. */
export interface Option {
  value: string;
  label: string;
}
