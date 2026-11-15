import { z } from 'zod';

import { client } from '@/shared/api/client';

/** A vocabulary domain. */
export const domainSchema = z.object({
  domain_id: z.string(),
  name: z.string(),
  description: z.string(),
});

export type Domain = z.infer<typeof domainSchema>;

const domainCreatedSchema = z.object({ domain_id: z.string() });

/**
 * Lists every live domain.
 *
 * @returns The domain rows.
 */
export async function fetchDomains(): Promise<Domain[]> {
  const response = await client.get('/vocabulary/domains');
  return domainSchema.array().parse(response.data);
}

/**
 * Reads one domain.
 *
 * @param domainId Id of the domain.
 * @returns The domain row.
 */
export async function fetchDomain(domainId: string): Promise<Domain> {
  const response = await client.get(`/vocabulary/domains/${domainId}`);
  return domainSchema.parse(response.data);
}

/**
 * Creates a domain.
 *
 * @param body Name and description.
 * @returns Id of the new domain.
 */
export async function createDomain(body: { name: string; description: string }): Promise<string> {
  const response = await client.post('/vocabulary/domains', body);
  return domainCreatedSchema.parse(response.data).domain_id;
}

/**
 * Renames a domain and/or changes its description.
 *
 * @param domainId Id of the domain.
 * @param body Fields to change.
 */
export async function changeDomain(
  domainId: string,
  body: { name?: string; description?: string },
): Promise<void> {
  await client.patch(`/vocabulary/domains/${domainId}`, body);
}

/**
 * Discards a domain with its terms.
 *
 * @param domainId Id of the domain.
 */
export async function discardDomain(domainId: string): Promise<void> {
  await client.delete(`/vocabulary/domains/${domainId}`);
}
