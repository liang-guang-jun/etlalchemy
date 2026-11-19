import { useMemo } from 'react';

import { useTargets } from '@/entities/comment';
import { urnReferences, urnsIn } from '@/shared/lib/urn';

/**
 * Builds the key a described target is indexed by.
 *
 * @param type Kind of the object.
 * @param id Id of the object.
 * @returns Key such as `table:96420819-…`.
 */
function refKey(type: string, id: string): string {
  return `${type}:${id}`;
}

/**
 * Resolves the object names of the URNs an answer links to.
 *
 * A URN carries the id of the object, not its name, while the reader wants the
 * name in the running text ("the schema `dev`"), so the names come from the same
 * target lookup the comment panel uses. A column or an entity URN already names
 * its object, and an id the read model does not know yet keeps the short label
 * the link was built with.
 *
 * @param text Markdown of the answer.
 * @returns The names keyed by the URN a link carries in its title.
 */
export function useUrnLabels(text: string): ReadonlyMap<string, string> {
  const targets = useMemo(() => urnsIn(text), [text]);
  const refs = useMemo(
    () => urnReferences(text).map((ref) => ({ targetType: ref.type, targetId: ref.id })),
    [text],
  );
  const described = useTargets(refs);

  return useMemo(() => {
    const names = new Map<string, string>();
    for (const description of described.data ?? []) {
      names.set(refKey(description.target_type, description.target_id), description.name);
    }
    const labels = new Map<string, string>();
    for (const target of targets) {
      const name =
        target.reference === null
          ? undefined
          : names.get(refKey(target.reference.type, target.reference.id));
      if (name !== undefined && name !== '') {
        labels.set(target.urn, name);
      }
    }
    return labels;
  }, [described.data, targets]);
}
