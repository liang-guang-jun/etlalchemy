/** Path of the connections list. */
export function ingestionPath(): string {
  return '/ingestion';
}

/** Path of one connection detail page. */
export function connectionPath(connectionId: string): string {
  return `${ingestionPath()}/${encodeURIComponent(connectionId)}`;
}

/** Path of the import wizard of one connection. */
export function importWizardPath(connectionId: string): string {
  return `${connectionPath(connectionId)}/new-import`;
}
