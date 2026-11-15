import { useMemo } from 'react';
import { useQueries } from '@tanstack/react-query';

import { fetchUser, userKeys, useUser, useUserSearch, type UserSummary } from '@/entities/user';
import { useDebounced } from '@/shared/lib/use-debounced';

/** How a user id is shown when it cannot be resolved. */
const UNKNOWN = 'User';

/**
 * Renders the author of a comment.
 *
 * `GET /iam/users/{id}` only needs a session, so any signed-in user can read the
 * name of whoever wrote a comment; the request is cached per id.
 *
 * @param userId Id of the author.
 * @returns The display name, or a short id while it loads or when it is unknown.
 */
export function useAuthorName(userId: string): string {
  const user = useUser(userId === '' ? null : userId);
  const data = user.data;
  if (data === undefined) {
    return `${UNKNOWN} ${userId.slice(0, 8)}`;
  }
  return data.display_name === '' ? data.username : data.display_name;
}

/**
 * Suggests users for the `@` token that is being typed.
 *
 * An empty term is queried too, so typing a bare `@` already lists the first
 * users; the request is debounced, and the cached answer is narrowed to the term
 * actually typed.
 *
 * @param term Text typed after the `@`.
 * @returns The suggestions and whether a request is in flight.
 */
export function useMentionSuggestions(term: string): {
  suggestions: UserSummary[];
  loading: boolean;
} {
  const debounced = useDebounced(term, 150);
  const search = useUserSearch(debounced);
  return {
    suggestions: narrowSuggestions(search.data ?? [], term),
    loading: search.isPending,
  };
}

/** A user a comment mentions, kept so the request can drop it again. */
export interface MentionPick {
  /** Id of the user. */
  id: string;
  /** Name written into the body as `@name`. */
  name: string;
}

/**
 * Finds the picked users that are still named in the body.
 *
 * Mentions are derived from the text instead of tracked blindly, so deleting the
 * `@name` token also drops the mention from the request.
 *
 * @param body Text of the comment.
 * @param picks Users picked from the suggestion list.
 * @returns The ids of the mentioned users, at most 20.
 */
export function resolveMentions(body: string, picks: readonly MentionPick[]): string[] {
  const ids: string[] = [];
  for (const pick of picks) {
    if (!body.includes(`@${pick.name}`) || ids.includes(pick.id)) {
      continue;
    }
    ids.push(pick.id);
    if (ids.length === 20) {
      break;
    }
  }
  return ids;
}

/**
 * Filters suggestions by the typed term, so the list narrows while typing.
 *
 * The endpoint already filters; this only drops the hits that no longer match
 * when the list is rendered from the previous request's cache.
 *
 * @param users Suggestions of the last request.
 * @param term Text typed after the `@`.
 * @returns Up to six users whose name or username contains the term.
 */
export function narrowSuggestions(users: readonly UserSummary[], term: string): UserSummary[] {
  const needle = term.trim().toLowerCase();
  return users
    .filter(
      (user) =>
        needle === '' ||
        user.display_name.toLowerCase().includes(needle) ||
        user.username.toLowerCase().includes(needle),
    )
    .slice(0, 6);
}

/**
 * Resolves several author names at once, for the panel search.
 *
 * @param ids Author ids of the threads and comments on screen.
 * @returns A map from user id to display name.
 */
export function useAuthorNames(ids: readonly string[]): Map<string, string> {
  const unique = useMemo(() => [...new Set(ids.filter((id) => id !== ''))], [ids]);
  const queries = useQueries({
    queries: unique.map((id) => ({
      queryKey: userKeys.detail(id),
      queryFn: () => fetchUser(id),
      staleTime: 5 * 60 * 1000,
    })),
    combine: (results) => results.map((result) => result.data),
  });

  return useMemo(() => {
    const names = new Map<string, string>();
    unique.forEach((id, index) => {
      const user = queries[index];
      names.set(id, user === undefined || user === null ? '' : user.display_name || user.username);
    });
    return names;
  }, [unique, queries]);
}
