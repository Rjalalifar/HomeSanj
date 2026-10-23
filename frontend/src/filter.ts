import type { SearchState } from './contracts.generated';
import type { Inventory, ResultRow } from './api';
import { normalize } from './api';
export function filterInventory(inventory:Inventory,state:SearchState):ResultRow[] {
  const c=state.property, words=normalize(state.query).match(/[\p{L}\p{N}_]+/gu)?.slice(0,30)??[];
  return inventory.properties.filter(p=>{
    if(p.dataset_version!==state.dataset_version) return false;
    if(c.max_deposit_toman!==null&&(p.deposit_toman===null||p.deposit_toman>c.max_deposit_toman)) return false;
    if(c.max_monthly_rent_toman!==null&&(p.monthly_rent_toman===null||p.monthly_rent_toman>c.max_monthly_rent_toman)) return false;
    if(c.min_area_m2!==null&&(p.area_m2===null||p.area_m2<c.min_area_m2)) return false;
    if(c.min_bedrooms!==null&&(p.bedrooms===null||p.bedrooms<c.min_bedrooms)) return false;
    if(c.parking_required===true&&p.parking!==true) return false;
    if(c.elevator_required===true&&p.elevator!==true) return false;
    if(state.selected_neighborhood_ids.length&&!state.selected_neighborhood_ids.some(id=>p.neighborhood_ids.includes(id))) return false;
    if(state.selected_district_ids.length&&!state.selected_district_ids.some(id=>p.district_ids.includes(id))) return false;
    const searchable=normalize(p.search_text??`${p.title_fa} ${(p.neighborhood_names??[]).join(' ')}`).match(/[\p{L}\p{N}_]+/gu)??[];
    return words.every(word=>searchable.some(token=>token.startsWith(word)));
  }).map(property=>({property,route_status:'not_evaluated',selected_itinerary:null}));
}
export function sortRows(rows:ResultRow[],state:SearchState):ResultRow[] {
  if (state.sort === 'stop_walk_time_asc' || state.sort === 'stop_distance_asc') {
    const value = (row: ResultRow) => state.sort === 'stop_distance_asc' ? row.accessibility?.straight_line_meters ?? null : row.accessibility?.status === 'ok' ? row.accessibility.walk_duration_seconds : null;
    return [...rows].sort((a, b) => {
      const left = value(a), right = value(b);
      if (left === null && right !== null) return 1;
      if (right === null && left !== null) return -1;
      if (left !== null && right !== null && left !== right) return left - right;
      return a.property.property_id.localeCompare(b.property.property_id, 'en');
    });
  }
  const base={balanced:[.30,.20,.25,.15,.10],lower_rent:[.60,.20,.10,.06,.04],faster_commute:[.15,.10,.55,.12,.08],less_walking:[.15,.10,.15,.52,.08],fewer_transfers:[.15,.10,.15,.10,.50]}[state.preference].slice();
  for(const soft of state.soft_preferences) {const i={lower_rent:0,faster_commute:2,less_walking:3,fewer_transfers:4}[soft as 'lower_rent'];if(i!==undefined&&soft!==state.preference) base[i]*=1.5;}
  if(!state.travel.destination) base.splice(2,3,0,0,0);
  const total=base.reduce((a,b)=>a+b,0),weights=base.map(value=>value/total);
  const scales=[state.property.max_monthly_rent_toman||30000000,state.property.max_deposit_toman||1000000000,state.travel.max_duration_seconds||3600,state.travel.max_walk_seconds||900,state.travel.max_transfers||3];
  const values=(row:ResultRow)=>[row.property.monthly_rent_toman,row.property.deposit_toman,row.selected_itinerary?.total_duration_seconds??null,row.selected_itinerary?.walk_duration_seconds??null,row.selected_itinerary?.transfers??null];
  const score=(row:ResultRow)=>values(row).reduce<number>((sum,value,i)=>sum+(value===null?1:Math.min(value/scales[i],1))*weights[i],0)-['parking','elevator'].filter(key=>state.soft_preferences.includes(key as 'parking')&&row.property[key as 'parking']===true).length*.025;
  const order={rent_asc:[0,1],deposit_asc:[1,0],travel_time_asc:[2,3,4,0],walk_time_asc:[3,2,0],transfers_asc:[4,2,3]}[state.sort as 'rent_asc'];
  return rows.map(row=>({...row,rank_score:score(row)})).sort((a,b)=>{
    if(state.sort==='recommended') {const diff=a.rank_score-b.rank_score;if(diff) return diff;}
    else for(const i of order) {const x=values(a)[i],y=values(b)[i];if(x===null&&y!==null)return 1;if(y===null&&x!==null)return -1;if(x!==null&&y!==null&&x!==y)return x-y;}
    return a.property.property_id<b.property.property_id?-1:1;
  });
}
