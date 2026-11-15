/** Controllers of the streams currently open, keyed by conversation id. */
const controllers = new Map<string, AbortController>();

/**
 * Registers a new controller for a conversation and aborts the previous one.
 *
 * One conversation runs one stream at a time; a second send replaces the first
 * instead of leaking its connection.
 *
 * @param conversationId Id of the conversation.
 * @returns The controller the caller must release when the stream settles.
 */
export function beginStream(conversationId: string): AbortController {
  controllers.get(conversationId)?.abort();
  const controller = new AbortController();
  controllers.set(conversationId, controller);
  return controller;
}

/**
 * Aborts the stream of a conversation, if any.
 *
 * @param conversationId Id of the conversation.
 */
export function abortStream(conversationId: string): void {
  controllers.get(conversationId)?.abort();
}

/**
 * Forgets a controller once its stream settled.
 *
 * The entry is only removed when it still belongs to this stream, so a slow
 * failure does not drop the controller of the run that replaced it.
 *
 * @param conversationId Id of the conversation.
 * @param controller Controller that settled.
 */
export function releaseStream(conversationId: string, controller: AbortController): void {
  if (controllers.get(conversationId) === controller) {
    controllers.delete(conversationId);
  }
}
