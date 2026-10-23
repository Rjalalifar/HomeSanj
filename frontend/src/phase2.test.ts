import { describe, expect, it } from 'vitest';
import type { SearchState } from './contracts.generated';
import type { Inventory } from './api';
import { filterInventory, sortRows } from './filter';
import { operation, patchState, reducer } from './state';

const defaults: SearchState = { accessibility: null, schema_version: '1.0.0', dataset_version: 'test', state_revision: 0, query: '', selected_neighborhood_ids: [], selected_district_ids: [], property: { max_deposit_toman: null, max_monthly_rent_toman: null, min_area_m2: null, min_bedrooms: null, parking_required: false, elevator_required: false }, travel: { destination: null, date: null, time: null, time_mode: 'DEPART_AT', timezone: 'Asia/Tehran', max_duration_seconds: null, max_walk_seconds: null, max_walk_meters: null, max_transfers: null, modes: [], include_walk_only: false, duration_scope: 'itinerary' }, preference: 'balanced', sort: 'recommended', soft_preferences: [] };
const inventory = { dataset_version: 'test', properties: [
  { property_id: 'a', dataset_version: 'test', title_fa: 'خانه', neighborhood_ids: ['n1'], district_ids: ['d1'], parking: null, monthly_rent_toman: null, deposit_toman: 10, bedrooms: 2, area_m2: 50 },
  { property_id: 'b', dataset_version: 'test', title_fa: 'خانه', neighborhood_ids: ['n2'], district_ids: ['d1'], parking: true, monthly_rent_toman: 5, deposit_toman: 20, bedrooms: 2, area_m2: 60 },
  { property_id: 'c', dataset_version: 'test', title_fa: 'خانه', neighborhood_ids: ['n3'], district_ids: ['d2'], parking: false, monthly_rent_toman: 2, deposit_toman: 10, bedrooms: 1, area_m2: 45 },
] } as Inventory;

describe('phase-two shared state and browser filtering', () => {
  it('combines neighborhoods by OR and districts by AND without erasing a contradiction', () => {
    const state = { ...defaults, selected_neighborhood_ids: ['n1', 'n2'], selected_district_ids: ['d1'] };
    expect(filterInventory(inventory, state).map(r => r.property.property_id)).toEqual(['a', 'b']);
    expect(filterInventory(inventory, { ...state, selected_district_ids: ['d2'] })).toEqual([]);
    expect(state.selected_neighborhood_ids).toEqual(['n1', 'n2']);
  });
  it('unknown active conditions do not pass; false means optional', () => {
    expect(filterInventory(inventory, { ...defaults, property: { ...defaults.property, max_monthly_rent_toman: 10 } }).map(r => r.property.property_id)).toEqual(['b', 'c']);
    expect(filterInventory(inventory, { ...defaults, property: { ...defaults.property, parking_required: true } }).map(r => r.property.property_id)).toEqual(['b']);
    expect(filterInventory(inventory, defaults)).toHaveLength(3);
  });
  it('orders null prices last and preserves immutable input', () => {
    const rows = filterInventory(inventory, defaults);
    expect(sortRows(rows, { ...defaults, sort: 'rent_asc' }).map(r => r.property.property_id)).toEqual(['c', 'b', 'a']);
    expect(rows[0].property.property_id).toBe('a');
  });
  it('removes travel limits while retaining an explicitly confirmed destination and time', () => {
    const state = patchState(defaults, defaults, [operation('travel.destination', { latitude: 35.7, longitude: 51.4, confirmed: true, label: 'Work' }), operation('travel.date', '2026-10-21'), operation('travel.time', '08:00'), operation('travel.max_walk_seconds', 1200)]);
    const cleared = reducer({ state, defaults, error: null }, { type: 'clear' }).state;
    expect(cleared.travel.destination).toEqual(state.travel.destination);
    expect(cleared.travel.date).toBe('2026-10-21');
    expect(cleared.travel.max_walk_seconds).toBeNull();
  });
  it('rejects fractional integer money and invalid dates before a state mutation', () => {
    expect(() => patchState(defaults, defaults, [operation('property.max_deposit_toman', 1.5)])).toThrow();
    expect(() => patchState(defaults, defaults, [operation('travel.date', '2026-02-31')])).toThrow();
    expect(() => patchState(defaults, defaults, [operation('arbitrary.sql', 'DROP')])).toThrow();
    expect(defaults.state_revision).toBe(0);
  });
});
