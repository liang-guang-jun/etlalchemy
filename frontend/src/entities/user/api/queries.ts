import { useQuery } from '@tanstack/react-query';

import { fetchUser, fetchUsers, searchUsers } from './fetchers';
import { userKeys } from './keys';

/**
 * Reads one user; skipped while the id is unknown.
 *
 * @param userId Id of the user, or `null` to skip the request.
 * @returns The query result of `GET /iam/users/{user_id}`.
 */
export function useUser(userId: string | null) {
  return useQuery({
    queryKey: userKeys.detail(userId ?? 'unknown'),
    queryFn: () => fetchUser(userId ?? ''),
    enabled: userId !== null,
  });
}

/**
 * Reads every live user. Only a system administrator may call it.
 *
 * @param enabled Whether the request should run.
 * @returns The query result of `GET /iam/users`.
 */
export function useUsers(enabled: boolean) {
  return useQuery({
    queryKey: userKeys.lists(),
    queryFn: fetchUsers,
    enabled,
  });
}

/**
 * Suggests users for an `@` mention.
 *
 * The term is optional: the endpoint answers the first users for an empty term,
 * which is what a bare `@` shows before anything is typed. Every signed-in user
 * may call it; only `GET /iam/users` is administrator-only.
 *
 * @param term Keyword typed after the `@`.
 * @param limit Maximum number of suggestions.
 * @returns The query result of `GET /iam/users/search`.
 */
export function useUserSearch(term: string, limit = 8) {
  const trimmed = term.trim();
  return useQuery({
    queryKey: userKeys.search(trimmed, limit),
    queryFn: () => searchUsers(trimmed, limit),
  });
}
