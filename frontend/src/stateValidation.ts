import type { SearchState } from './contracts.generated';

export function validateScalarState(state: SearchState): void {
  const integerValues = [state.property.max_deposit_toman, state.property.max_monthly_rent_toman, state.property.min_bedrooms, state.travel.max_duration_seconds, state.travel.max_walk_seconds, state.travel.max_walk_meters, state.travel.max_transfers];
  if (integerValues.some(value => value !== null && (!Number.isInteger(value) || value < 0 || value > 9000000000000000))) throw new Error('این مقدار باید عدد صحیحِ غیرمنفی و در محدودهٔ مجاز باشد.');
  const date = state.travel.date;
  if (date && (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date)) throw new Error('تاریخ سفر معتبر نیست.');
  if (state.travel.time && !/^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$/.test(state.travel.time)) throw new Error('ساعت سفر معتبر نیست.');
  const destination = state.travel.destination;
  if (destination && (destination.confirmed !== true || !Number.isFinite(destination.latitude) || !Number.isFinite(destination.longitude) || Math.abs(destination.latitude) > 90 || Math.abs(destination.longitude) > 180)) throw new Error('مختصات مقصد معتبر نیست.');
}

export function clearedState(state: SearchState, defaults: SearchState): SearchState {
  return { ...structuredClone(defaults), accessibility: structuredClone(state.accessibility), travel: { ...structuredClone(defaults.travel), destination: structuredClone(state.travel.destination), date: state.travel.date, time: state.travel.time, time_mode: state.travel.time_mode }, preference: state.preference, soft_preferences: structuredClone(state.soft_preferences), state_revision: state.state_revision + 1 };
}
