import { describe, expect, it } from 'vitest';

import {
  clampPanelSize,
  minimumPanelSize,
  PANEL_SIZE_KEY,
  readPanelSize,
  readWidgetPosition,
  WIDGET_POSITION_KEY,
  writePanelSize,
  writeWidgetPosition,
  type PanelSize,
  type WidgetPosition,
} from './position';

/** In-memory `Storage` used by the cases. */
function memoryStorage(initial: Record<string, string> = {}): Storage {
  const values = new Map(Object.entries(initial));
  return {
    get length() {
      return values.size;
    },
    clear: () => {
      values.clear();
    },
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    removeItem: (key: string) => {
      values.delete(key);
    },
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

const VIEWPORT = { width: 1440, height: 900 };

describe('readWidgetPosition', () => {
  it('defaults to the bottom-right corner', () => {
    expect(readWidgetPosition(memoryStorage(), VIEWPORT)).toEqual({ x: 1360, y: 820 });
  });

  it('restores a stored position', () => {
    const storage = memoryStorage({
      [WIDGET_POSITION_KEY]: JSON.stringify({ x: 40, y: 300 } satisfies WidgetPosition),
    });

    expect(readWidgetPosition(storage, VIEWPORT)).toEqual({ x: 40, y: 300 });
  });

  it('clamps a position stored on a larger screen', () => {
    const storage = memoryStorage({
      [WIDGET_POSITION_KEY]: JSON.stringify({ x: 3000, y: 2000 }),
    });

    expect(readWidgetPosition(storage, VIEWPORT)).toEqual({ x: 1384, y: 844 });
  });

  it('ignores a corrupted entry', () => {
    const storage = memoryStorage({ [WIDGET_POSITION_KEY]: 'not json' });

    expect(readWidgetPosition(storage, VIEWPORT)).toEqual({ x: 1360, y: 820 });
  });
});

describe('writeWidgetPosition', () => {
  it('round-trips the position', () => {
    const storage = memoryStorage();

    writeWidgetPosition({ x: 12, y: 34 }, storage);

    expect(readWidgetPosition(storage, VIEWPORT)).toEqual({ x: 12, y: 34 });
  });

  it('survives a storage that throws', () => {
    const broken = memoryStorage();
    broken.setItem = () => {
      throw new Error('quota exceeded');
    };

    expect(() => {
      writeWidgetPosition({ x: 1, y: 2 }, broken);
    }).not.toThrow();
  });
});

describe('minimumPanelSize', () => {
  it('keeps a quarter of a wide viewport', () => {
    expect(minimumPanelSize(VIEWPORT)).toEqual({ width: 360, height: 320 });
  });

  it('falls back to a readable floor on a narrow viewport', () => {
    // A quarter of 800 is 200, which is narrower than the floor.
    expect(minimumPanelSize({ width: 800, height: 600 }).width).toBe(320);
  });
});

describe('clampPanelSize', () => {
  it('raises a requested size to the minimum', () => {
    const requested: PanelSize = { width: 120, height: 100 };

    expect(clampPanelSize(requested, VIEWPORT)).toEqual({ width: 360, height: 320 });
  });

  it('keeps a size inside the viewport', () => {
    const requested: PanelSize = { width: 5000, height: 5000 };

    expect(clampPanelSize(requested, VIEWPORT)).toEqual({ width: 1416, height: 876 });
  });

  it('keeps a size that already fits', () => {
    const requested: PanelSize = { width: 720, height: 640 };

    expect(clampPanelSize(requested, VIEWPORT)).toEqual(requested);
  });
});

describe('readPanelSize', () => {
  it('restores a stored size', () => {
    const storage = memoryStorage({
      [PANEL_SIZE_KEY]: JSON.stringify({ width: 720, height: 640 }),
    });

    expect(readPanelSize(storage, VIEWPORT)).toEqual({ width: 720, height: 640 });
  });

  it('clamps a stored size that no longer fits', () => {
    const storage = memoryStorage() as Storage;
    writePanelSize({ width: 900, height: 700 }, storage);

    expect(readPanelSize(storage, { width: 800, height: 500 })).toEqual({
      width: 776,
      height: 476,
    });
  });

  it('falls back to the default on a corrupted entry', () => {
    const storage = memoryStorage({ [PANEL_SIZE_KEY]: 'nope' });

    expect(readPanelSize(storage, VIEWPORT)).toEqual({ width: 400, height: 600 });
  });
});
