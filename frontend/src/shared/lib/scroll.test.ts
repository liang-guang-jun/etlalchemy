import { describe, expect, it } from 'vitest';

import { keepInView, scrollParent } from './scroll';

/** Builds a scroller with the metrics jsdom does not lay out. */
function makeScroller(metrics: { scrollHeight: number; clientHeight: number }): {
  scroller: HTMLDivElement;
  bottom: HTMLDivElement;
  read: () => number;
} {
  const scroller = document.createElement('div');
  scroller.style.overflowY = 'auto';
  let top = 0;
  Object.defineProperty(scroller, 'scrollHeight', { value: metrics.scrollHeight });
  Object.defineProperty(scroller, 'clientHeight', { value: metrics.clientHeight });
  Object.defineProperty(scroller, 'scrollTop', {
    get: () => top,
    set: (value: number) => {
      top = value;
    },
  });
  const bottom = document.createElement('div');
  scroller.append(bottom);
  document.body.append(scroller);
  return { scroller, bottom, read: () => top };
}

describe('scrollParent', () => {
  it('walks up to the element that scrolls vertically', () => {
    const { scroller, bottom } = makeScroller({ scrollHeight: 900, clientHeight: 400 });

    expect(scrollParent(bottom)).toBe(scroller);

    scroller.remove();
  });

  it('answers null when nothing scrolls', () => {
    const detached = document.createElement('div');

    expect(scrollParent(detached)).toBeNull();
  });
});

describe('keepInView', () => {
  it('follows the newest content while the answer streams', () => {
    const { bottom, read } = makeScroller({ scrollHeight: 900, clientHeight: 400 });

    keepInView(bottom, true, false);

    expect(read()).toBe(900);
  });

  it('leaves a reader who scrolled up alone', () => {
    const { bottom, read } = makeScroller({ scrollHeight: 900, clientHeight: 400 });

    keepInView(bottom, false, false);

    expect(read()).toBe(0);
  });

  it('sticks to the bottom when the reader is already there', () => {
    const { scroller, bottom, read } = makeScroller({ scrollHeight: 900, clientHeight: 400 });
    scroller.scrollTop = 500;

    keepInView(bottom, false, false);

    // 900 - 500 - 400 = 0, well inside the follow threshold.
    expect(read()).toBe(900);
  });

  it('jumps to the end when the caller asks for it', () => {
    const { bottom, read } = makeScroller({ scrollHeight: 900, clientHeight: 400 });

    keepInView(bottom, false, true);

    expect(read()).toBe(900);
  });
});
