import { validateScalarState, clearedState } from './stateValidation';
﻿import type { PatchOperation, SearchState } from './contracts.generated';
export type Store={state:SearchState;defaults:SearchState;error:string|null};
export type Action={type:'patch';operations:PatchOperation[]}|{type:'replace';state:SearchState}|{type:'clear'};
const allowed=new Set(['query','selected_neighborhood_ids','selected_district_ids','preference','sort','soft_preferences','property.max_deposit_toman','property.max_monthly_rent_toman','property.min_area_m2','property.min_bedrooms','property.parking_required','property.elevator_required','travel.destination','travel.date','travel.time','travel.time_mode','travel.max_duration_seconds','travel.max_walk_seconds','travel.max_walk_meters','travel.max_transfers','travel.modes','travel.include_walk_only']);
export function patchState(state:SearchState,defaults:SearchState,operations:PatchOperation[]):SearchState {
  const next=structuredClone(state);
  for(const operation of operations) {
    if(!allowed.has(operation.field)) throw new Error('شرط پشتیبانی نمی‌شود.');
    const [group,key]=operation.field.split('.');
    const target=(key?next[group as 'property'|'travel']:next) as unknown as Record<string,unknown>;
    const source=(key?defaults[group as 'property'|'travel']:defaults) as unknown as Record<string,unknown>;
    const field=key??group;target[field]=operation.remove?structuredClone(source[field]):structuredClone(operation.value);
  }
  for(const [key,value] of Object.entries(next.property)) {
    if(key.endsWith('_required')) {if(value!==null&&typeof value!=='boolean') throw new Error('شرط امکانات نامعتبر است.');}
    else if(value!==null&&(typeof value!=='number'||!Number.isFinite(value)||value<0)) throw new Error('عدد باید مثبت یا صفر باشد.');
  }
  for(const key of ['max_duration_seconds','max_walk_seconds','max_walk_meters','max_transfers'] as const) {const value=next.travel[key];if(value!==null&&(!Number.isFinite(value)||value<0)) throw new Error('حد سفر نامعتبر است.');}
  if(next.travel.destination&&!next.accessibility?.enabled&&(!next.travel.date||!next.travel.time)) throw new Error('تاریخ و ساعت سفر را مشخص کنید.');
  if(!next.travel.destination&&(next.travel.max_duration_seconds!==null||next.travel.max_walk_seconds!==null||next.travel.max_walk_meters!==null||next.travel.max_transfers!==null||next.travel.modes.length||next.travel.include_walk_only)) throw new Error('ابتدا مقصد، تاریخ و ساعت را تأیید کنید.');
  validateScalarState(next);
  if(next.travel.time?.length===5) next.travel.time+=':00';next.state_revision=state.state_revision+1;return next;
}
export function reducer(store:Store,action:Action):Store {
  try {
    if(action.type==='replace') return {...store,state:action.state,error:null};
    if(action.type==='clear') return {...store,state:clearedState(store.state,store.defaults),error:null};
    return {...store,state:patchState(store.state,store.defaults,action.operations),error:null};
  } catch(error) {return {...store,error:(error as Error).message};}
}
export const operation=(field:string,value:unknown):PatchOperation=>({field,value,remove:false});
export const stateKey=(state:SearchState)=>JSON.stringify({...state,state_revision:0});
export const travelSort=(state:SearchState)=>['travel_time_asc','walk_time_asc','transfers_asc'].includes(state.sort);
