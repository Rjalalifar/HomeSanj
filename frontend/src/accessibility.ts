import type { Destination, SearchState } from './contracts.generated';
import { stateKey } from './state';

export const destinationStorageKey = 'homesanj.regular-destination.v1';
type DestinationStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export function readDestination(storage: DestinationStorage): Destination | null {
  try {
    const value: unknown = JSON.parse(storage.getItem(destinationStorageKey) ?? 'null');
    if (!value || typeof value !== 'object') return null;
    const candidate = value as Record<string, unknown>;
    if (candidate.confirmed !== true || typeof candidate.latitude !== 'number' || typeof candidate.longitude !== 'number' || !Number.isFinite(candidate.latitude) || !Number.isFinite(candidate.longitude) || Math.abs(candidate.latitude) > 90 || Math.abs(candidate.longitude) > 180 || typeof candidate.label !== 'string') return null;
    return { latitude: candidate.latitude, longitude: candidate.longitude, label: candidate.label.slice(0, 120), confirmed: true };
  } catch { return null; }
}

export function writeDestination(storage: DestinationStorage, destination: Destination | null): void {
  if (destination === null) storage.removeItem(destinationStorageKey);
  else storage.setItem(destinationStorageKey, JSON.stringify(destination));
}

export function initializeAccessibility(initial: SearchState): SearchState {
  let destination: Destination | null = null;
  try { destination = readDestination(window.localStorage); } catch { /* Search remains available when browser storage is restricted. */ }
  return { ...initial, accessibility: { semantics_version: 'accessibility-1', enabled: true, time_policy: 'request_execution', effective_at: null }, travel: { ...initial.travel, destination, date: null, time: null, time_mode: 'DEPART_AT' } };
}

export function accessibilitySearchKey(state: SearchState): string {
  const normalized = structuredClone(state);
  normalized.sort = 'recommended';
  if (normalized.accessibility?.enabled) {
    normalized.accessibility.effective_at = null;
    normalized.travel.date = null;
    normalized.travel.time = null;
  }
  return stateKey(normalized);
}

export function accessibilitySorts(hasDestination: boolean): Array<{ value: SearchState['sort']; label: string }> {
  return [
    { value: 'recommended', label: 'پیشنهادی' }, { value: 'rent_asc', label: 'اجاره کمتر' }, { value: 'deposit_asc', label: 'ودیعه کمتر' },
    ...(hasDestination ? [
      { value: 'travel_time_asc' as const, label: 'زمان سفر کمتر تا مقصد' }, { value: 'walk_time_asc' as const, label: 'پیاده‌روی کمتر تا مقصد' },
    ] : [
      { value: 'stop_walk_time_asc' as const, label: 'پیاده‌روی کمتر تا حمل‌ونقل عمومی' },
    ]),
  ];
}
