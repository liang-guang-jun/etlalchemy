import { MarkdownEditor } from '@/shared/ui/markdown-editor';

export interface MarkdownDescriptionProps {
  /** Current markdown source. */
  value: string;
  /** Disables the commit buttons while a request is in flight. */
  saving?: boolean;
  /** Called with the edited markdown when the editor commits. */
  onSave: (value: string) => void;
}

/**
 * Renders the editable markdown description shared by the catalog pages.
 *
 * @param props Component props.
 * @returns The markdown description block.
 */
export function MarkdownDescription({ value, saving = false, onSave }: MarkdownDescriptionProps) {
  return (
    <MarkdownEditor
      value={value}
      editable
      saving={saving}
      label="Description"
      placeholder="Describe this resource in markdown…"
      onSave={onSave}
    />
  );
}
