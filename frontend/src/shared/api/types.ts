/** Response shape of the commands that answer with a bare acknowledgement. */
export interface OkResponse {
  ok: boolean;
}

/** Offset pagination accepted by the list endpoints. */
export interface PageParams {
  limit?: number;
  offset?: number;
}
