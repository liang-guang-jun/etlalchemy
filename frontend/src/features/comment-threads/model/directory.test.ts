import { describe, expect, it } from 'vitest';

import type { UserSummary } from '@/entities/user';
import { narrowSuggestions, resolveMentions, type MentionPick } from './directory';

const pick = (id: string, name: string): MentionPick => ({ id, name });

const summary = (id: string, name: string): UserSummary => ({
  user_id: id,
  username: name.toLowerCase().replace(' ', '.'),
  display_name: name,
});

describe('resolveMentions', () => {
  it('keeps the picks that are still named in the body', () => {
    const picks = [pick('u1', 'Ada Lovelace'), pick('u2', 'Grace Hopper')];

    expect(resolveMentions('Thanks @Grace Hopper, please check', picks)).toEqual(['u2']);
  });

  it('drops a pick whose token was deleted again', () => {
    expect(resolveMentions('Thanks, nothing to add', [pick('u1', 'Ada Lovelace')])).toEqual([]);
  });

  it('keeps the order the users were picked in and ignores duplicates', () => {
    const picks = [
      pick('u2', 'Grace Hopper'),
      pick('u1', 'Ada Lovelace'),
      pick('u2', 'Grace Hopper'),
    ];

    expect(resolveMentions('@Grace Hopper and @Ada Lovelace', picks)).toEqual(['u2', 'u1']);
  });

  it('caps the list at twenty users', () => {
    const picks = Array.from({ length: 25 }, (_, index) =>
      pick(`m${String(index)}`, `U${String(index)}`),
    );
    const body = picks.map((entry) => `@${entry.name}`).join(' ');

    expect(resolveMentions(body, picks)).toHaveLength(20);
  });
});

describe('narrowSuggestions', () => {
  const USERS = [
    summary('u1', 'Ada Lovelace'),
    summary('u2', 'Grace Hopper'),
    summary('u3', 'Alan Turing'),
  ];

  it('matches the display name case-insensitively', () => {
    expect(narrowSuggestions(USERS, 'gra').map((row) => row.user_id)).toEqual(['u2']);
  });

  it('matches the username', () => {
    expect(narrowSuggestions(USERS, 'alan.').map((row) => row.user_id)).toEqual(['u3']);
  });

  it('returns at most six users', () => {
    const many = Array.from({ length: 9 }, (_, index) =>
      summary(`m${String(index)}`, `U${String(index)}`),
    );

    expect(narrowSuggestions(many, '')).toHaveLength(6);
  });

  it('returns nothing when no one matches', () => {
    expect(narrowSuggestions(USERS, 'zz')).toEqual([]);
  });
});
