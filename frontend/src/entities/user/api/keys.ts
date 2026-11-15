/** Query keys of the user entity. */
export const userKeys = {
  all: ['user'] as const,
  lists: () => [...userKeys.all, 'list'] as const,
  detail: (userId: string) => [...userKeys.all, 'detail', userId] as const,
  search: (term: string, limit: number) => [...userKeys.all, 'search', term, limit] as const,
};
