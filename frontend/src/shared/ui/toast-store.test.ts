import { afterEach, describe, expect, it, vi } from 'vitest';

import { toast, useToastStore } from './toast-store';

afterEach(() => {
  useToastStore.setState({ items: [] });
  vi.useRealTimers();
});

describe('toast store', () => {
  it('shows one toast per message while it is still visible', () => {
    // Nine objects of one answer used to raise nine identical errors, which a
    // reader cannot act on and cannot dismiss fast enough.
    toast.error('Input should be a valid UUID');
    toast.error('Input should be a valid UUID');
    toast.error('Input should be a valid UUID');

    expect(useToastStore.getState().items).toHaveLength(1);
  });

  it('shows the message again once it was dismissed', () => {
    toast.error('retry failed');
    const [item] = useToastStore.getState().items;
    useToastStore.getState().dismiss(item?.id ?? '');

    toast.error('retry failed');

    expect(useToastStore.getState().items).toHaveLength(1);
  });

  it('keeps different messages apart', () => {
    toast.error('first failure');
    toast.error('second failure');

    expect(useToastStore.getState().items.map((item) => item.message)).toEqual([
      'first failure',
      'second failure',
    ]);
  });

  it('keeps an error and a success with the same text apart', () => {
    toast.error('done');
    toast.success('done');

    expect(useToastStore.getState().items).toHaveLength(2);
  });

  it('dismisses one toast', () => {
    toast.info('only one');
    const [item] = useToastStore.getState().items;

    useToastStore.getState().dismiss(item?.id ?? '');

    expect(useToastStore.getState().items).toHaveLength(0);
  });
});
