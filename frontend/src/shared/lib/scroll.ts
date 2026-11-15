/** Distance from the bottom below which the view counts as "following". */
const FOLLOW_THRESHOLD = 160;

/**
 * Returns the nearest ancestor that scrolls vertically.
 *
 * @param node Element to start from.
 * @returns The scrolling ancestor, or `null` when nothing scrolls.
 */
export function scrollParent(node: HTMLElement | null): HTMLElement | null {
  let current = node?.parentElement ?? null;
  while (current !== null) {
    const overflow = window.getComputedStyle(current).overflowY;
    if (overflow === 'auto' || overflow === 'scroll') {
      return current;
    }
    current = current.parentElement;
  }
  return null;
}

/**
 * Keeps the newest content of a streaming answer in view.
 *
 * A reader who scrolled up is not dragged back down unless the answer is still
 * streaming, which is when "latest" is what they are watching.
 *
 * @param node Element that marks the end of the content.
 * @param streaming Whether the run is producing tokens right now.
 * @param follow Always scroll, for example right after a conversation changed.
 */
export function keepInView(node: HTMLElement | null, streaming: boolean, follow: boolean): void {
  if (node === null) {
    return;
  }
  const scroller = scrollParent(node);
  if (scroller === null) {
    // jsdom has no `scrollIntoView`; the guard keeps the tests quiet.
    if (typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'end' });
    }
    return;
  }
  const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
  if (follow || streaming || remaining < FOLLOW_THRESHOLD) {
    scroller.scrollTop = scroller.scrollHeight;
  }
}
