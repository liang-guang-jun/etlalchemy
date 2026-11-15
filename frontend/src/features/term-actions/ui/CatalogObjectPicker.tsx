import { CatalogObjectTree, type CatalogObjectKind } from '@/entities/catalog';
import { Button, Dialog } from '@/shared/ui';

/** One picked catalog object. */
export interface CatalogObjectSelection {
  /** One of `catalog`, `schema`, `table` or `field`. */
  kind: CatalogObjectKind;
  /** Id of the catalog, schema or table, or of the owning table for a field. */
  targetId: string;
  /** Field name for `field` selections, empty otherwise. */
  fieldName: string;
  /** Human readable path such as `analytics / sales / orders / customer_id`. */
  label: string;
}

export interface CatalogObjectPickerProps {
  open: boolean;
  onSelect: (selection: CatalogObjectSelection) => void;
  onClose: () => void;
}

/**
 * Links a term to a catalog object.
 *
 * The dialog holds the catalog tree the resource explorer of the data catalog
 * shows, so any level — catalog, schema, table or column — can be linked by
 * clicking it, and a search keeps the hierarchy of every hit.
 *
 * @param props Component props.
 * @returns The picker dialog.
 */
export function CatalogObjectPicker({ open, onSelect, onClose }: CatalogObjectPickerProps) {
  return (
    <Dialog
      open={open}
      title="Link a catalog object"
      description="Click the object to link; catalogs, schemas, tables and columns can all be linked."
      onClose={onClose}
      footer={
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
      }
    >
      <CatalogObjectTree
        className="h-80"
        onSelect={(object) => {
          onSelect({
            kind: object.kind,
            targetId: object.targetId,
            fieldName: object.fieldName,
            label: object.path,
          });
          onClose();
        }}
      />
    </Dialog>
  );
}
