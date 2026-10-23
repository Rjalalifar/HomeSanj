import { describe, expect, it } from 'vitest';
import { destinationStorageKey, readDestination, writeDestination, accessibilitySorts, accessibilitySearchKey } from './accessibility';
import type { SearchState } from './contracts.generated';

function storage() {
  const values = new Map<string, string>();
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); }, removeItem: (key: string) => { values.delete(key); } };
}

describe('regular destination and accessibility presentation', () => {
  it('persists one validated destination and removes it without touching unrelated storage', () => {
    const saved = storage(); saved.setItem('unrelated', 'kept');
    const first = { latitude: 35.7, longitude: 51.4, label: 'دفتر', confirmed: true as const };
    writeDestination(saved, first); expect(readDestination(saved)).toEqual(first);
    const next = { ...first, longitude: 51.5, label: 'مقصد تازه' };
    writeDestination(saved, next); expect(readDestination(saved)).toEqual(next);
    writeDestination(saved, null); expect(readDestination(saved)).toBeNull(); expect(saved.getItem('unrelated')).toBe('kept');
  });
  it('does not accept corrupt or unconfirmed saved coordinates', () => {
    const saved = storage(); saved.setItem(destinationStorageKey, '{broken'); expect(readDestination(saved)).toBeNull();
    saved.setItem(destinationStorageKey, JSON.stringify({ latitude: 190, longitude: 51, confirmed: true, label: 'bad' })); expect(readDestination(saved)).toBeNull();
    saved.setItem(destinationStorageKey, JSON.stringify({ latitude: 35, longitude: 51, confirmed: false, label: 'draft' })); expect(readDestination(saved)).toBeNull();
  });
  it('offers only the accessibility sorts that have meaning for the destination context', () => {
    const nearby = accessibilitySorts(false).map(value => value.value), destination = accessibilitySorts(true).map(value => value.value);
    expect(nearby).toContain('stop_distance_asc'); expect(nearby).toContain('stop_walk_time_asc'); expect(nearby).not.toContain('travel_time_asc');
    expect(destination).toContain('travel_time_asc'); expect(destination).toContain('walk_time_asc'); expect(destination).not.toContain('stop_distance_asc');
    expect([...nearby, ...destination]).not.toContain('transfers_asc');
  });
  it('retains snapshot identity across sort changes and server execution time materialization', () => {
    const state = { state_revision: 0, sort: 'recommended', accessibility: { semantics_version: 'accessibility-1', enabled: true, time_policy: 'request_execution', effective_at: null }, travel: { date: null, time: null, destination: null } } as unknown as SearchState;
    const materialized = { ...state, state_revision: 3, sort: 'stop_distance_asc', accessibility: { ...state.accessibility!, effective_at: '2026-10-21T10:00:00+03:30' }, travel: { ...state.travel, date: '2026-10-21', time: '10:00:00' } } as SearchState;
    expect(accessibilitySearchKey(state)).toBe(accessibilitySearchKey(materialized));
    expect(accessibilitySearchKey({ ...materialized, travel: { ...materialized.travel, destination: { latitude: 35.7, longitude: 51.4, label: 'office', confirmed: true } } })).not.toBe(accessibilitySearchKey(state));
  });
});
