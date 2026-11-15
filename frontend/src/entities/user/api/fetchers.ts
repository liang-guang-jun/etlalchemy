import { client } from '@/shared/api/client';

import {
  userResponseSchema,
  userSummarySchema,
  type UserResponse,
  type UserSummary,
} from './schema';

/**
 * Reads one user.
 *
 * @param userId Id of the user.
 * @returns The user row.
 */
export async function fetchUser(userId: string): Promise<UserResponse> {
  const response = await client.get(`/iam/users/${userId}`);
  return userResponseSchema.parse(response.data);
}

/**
 * Lists every live user. Requires a system administrator session.
 *
 * @returns The user rows.
 */
export async function fetchUsers(): Promise<UserResponse[]> {
  const response = await client.get('/iam/users');
  return userResponseSchema.array().parse(response.data);
}

/**
 * Suggests users for an `@` mention. Any signed-in user may call it.
 *
 * @param term Keyword matched against the name, username and email.
 * @param limit Maximum number of suggestions.
 * @returns The matching users, reduced to what a mention needs.
 */
export async function searchUsers(term: string, limit = 8): Promise<UserSummary[]> {
  const response = await client.get('/iam/users/search', { params: { term, limit } });
  return userSummarySchema.array().parse(response.data);
}
