import { useQuery } from '@tanstack/react-query';

import {
  fetchConnection,
  fetchConnections,
  fetchImportRun,
  fetchImportRuns,
  fetchSourceKinds,
  fetchSourceProfiles,
  inspectSource,
  planImport,
  type ImportRequest,
  type InspectParams,
} from './api';

/** Query keys of the ingestion entity. */
export const ingestionKeys = {
  all: ['ingestion'] as const,
  connections: () => [...ingestionKeys.all, 'connections'] as const,
  connection: (connectionId: string) => [...ingestionKeys.all, 'connection', connectionId] as const,
  kinds: () => [...ingestionKeys.all, 'kinds'] as const,
  profiles: (kind: string) => [...ingestionKeys.all, 'profiles', kind] as const,
  inspect: (connectionId: string, params: InspectParams) =>
    [...ingestionKeys.all, 'inspect', connectionId, params] as const,
  plan: (connectionId: string, body: ImportRequest) =>
    [...ingestionKeys.all, 'plan', connectionId, body] as const,
  runs: (connectionId?: string) => [...ingestionKeys.all, 'runs', connectionId ?? 'all'] as const,
  run: (runId: string) => [...ingestionKeys.all, 'run', runId] as const,
};

/** How often a run that is still pending is polled, in milliseconds. */
export const RUN_POLL_MS = 2_000;

/**
 * Lists every live connection.
 *
 * @returns The query result of `GET /ingestion/connections`.
 */
export function useConnections() {
  return useQuery({ queryKey: ingestionKeys.connections(), queryFn: fetchConnections });
}

/**
 * Reads one connection.
 *
 * @param connectionId Id of the connection.
 * @returns The query result of `GET /ingestion/connections/{connection_id}`.
 */
export function useConnection(connectionId: string) {
  return useQuery({
    queryKey: ingestionKeys.connection(connectionId),
    queryFn: () => fetchConnection(connectionId),
  });
}

/**
 * Lists the source kinds the server supports.
 *
 * @returns The query result of `GET /ingestion/source-kinds`.
 */
export function useSourceKinds() {
  return useQuery({ queryKey: ingestionKeys.kinds(), queryFn: fetchSourceKinds });
}

/**
 * Lists the local credential profiles of a source kind.
 *
 * @param kind Source kind, for example `databricks`.
 * @param enabled Whether the caller can read that store.
 * @returns The query result of `GET /ingestion/source-profiles`.
 */
export function useSourceProfiles(kind: string, enabled = true) {
  return useQuery({
    queryKey: ingestionKeys.profiles(kind),
    queryFn: () => fetchSourceProfiles(kind),
    enabled,
    staleTime: 30_000,
  });
}

/**
 * Inspects one level of a source tree.
 *
 * @param connectionId Id of the connection.
 * @param params Deepest node to inspect.
 * @param enabled Whether the caller has expanded that node.
 * @returns The query result of the inspect route.
 */
export function useSourceInspect(connectionId: string, params: InspectParams, enabled = true) {
  return useQuery({
    queryKey: ingestionKeys.inspect(connectionId, params),
    queryFn: () => inspectSource(connectionId, params),
    enabled,
    staleTime: 60_000,
  });
}

/**
 * Previews an import for the confirmation step.
 *
 * @param connectionId Id of the connection.
 * @param body Import body; the query stays idle while `enabled` is false.
 * @param enabled Whether the preview should run.
 * @returns The query result of the plan route.
 */
export function useImportPlan(connectionId: string, body: ImportRequest, enabled: boolean) {
  return useQuery({
    queryKey: ingestionKeys.plan(connectionId, body),
    queryFn: () => planImport(connectionId, body),
    enabled,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Lists import runs of one connection.
 *
 * @param connectionId Id of the connection, or `undefined` for every run.
 * @param polling Whether runs that are still pending should be re-read.
 * @returns The query result of `GET /ingestion/runs`.
 */
export function useImportRuns(connectionId?: string, polling = false) {
  return useQuery({
    queryKey: ingestionKeys.runs(connectionId),
    queryFn: () => fetchImportRuns(connectionId),
    refetchInterval: (query) =>
      polling && (query.state.data ?? []).some((run) => run.status === 'pending')
        ? RUN_POLL_MS
        : false,
  });
}

/**
 * Reads one import run and polls it until it leaves `pending`.
 *
 * @param runId Id of the run; an empty string disables the query.
 * @returns The query result of `GET /ingestion/runs/{run_id}`.
 */
export function useImportRun(runId: string) {
  return useQuery({
    queryKey: ingestionKeys.run(runId),
    queryFn: () => fetchImportRun(runId),
    enabled: runId !== '',
    refetchInterval: (query) => (query.state.data?.status === 'pending' ? RUN_POLL_MS : false),
  });
}
