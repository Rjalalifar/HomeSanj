import type { SearchState, PropertyListing, Itinerary, PatchOperation } from './contracts.generated';
import type { Feature, Polygon, MultiPolygon } from 'geojson';
import booleanPointInPolygon from '@turf/boolean-point-in-polygon';
export type { Itinerary } from './contracts.generated';
export type Boundary = Feature<Polygon | MultiPolygon, {id:string; name_fa:string; name_normalized:string; district_no:number; quality_flags:string[]}>;
export type AccessibilityStop = {stop_type?:'metro'|'bus'; stop_id?:string; id?:string; name?:string; name_fa?:string; modes?:string[]; latitude?:number; longitude?:number};
export type PropertyAccessibility = {semantics_version:string; mode:'destination'|'nearby_stop'; status:string; nearest_stop:AccessibilityStop|null; walking_stop:AccessibilityStop|null; total_duration_seconds:number|null; walk_duration_seconds:number|null; walk_distance_meters:number|null; straight_line_meters:number|null; calculated_at:string|null; effective_at:string|null; cache_policy_version:string};
export type ResultRow = {property:PropertyListing; route_status:string; selected_itinerary:Itinerary|null; rank_score?:number; ranking_factors?:Record<string,{value:number|null;weight:number;cost:number}>; qualifying_itineraries?:Itinerary[]; accessibility?:PropertyAccessibility};
export type SearchResult = {task_id:string; request_id:string; snapshot_id:string; state:SearchState; candidate_count:number; evaluated_count:number; completion_status:string; subset_method:string; ranking_scope:string; warnings:string[]; results:ResultRow[]; result_count:number; excluded_evaluations:Array<{property_id?:string;status:string}>; unverified_results?:ResultRow[]; unverified_count?:number; semantic?:{status:string;metadata?:Record<string,unknown>;retrieved_count?:number;reason?:string}; cache_hits?:number; cache_misses?:number; accessibility?:{semantics_version:string; mode:'destination'|'nearby_stop'; effective_at:string|null; time_policy:string; stops_status?:string}};
export type Health = {dataset_version:string; listing_count:number; otp:{configured:boolean; supported_modes:string[]; fixture_mode:boolean; root_reachable:boolean|null; routing_api_verified:boolean; status:string; verified_at?:string; schedule_basis?:string; transfer_count_available?:boolean}; llm:{mode:string; enabled:boolean}; advanced?:{ai_enabled:boolean;semantic_configured:boolean};};
export type Inventory = {dataset_version:string; inventory_version:string; boundary_version:string; count:number; properties:Array<PropertyListing & {search_text?:string;neighborhood_names?:string[]}>};
export type IntentProposal = {operations:PatchOperation[]; clarifications:Array<{field:string;message:string;candidates?:Array<{id:string;name:string;source_district_no:number}>}>;soft_preferences:string[];semantic_text:string;requires_confirmation:boolean;search_pending:boolean;notices:string[];mode:string};
export type Explanation = {request_id:string;snapshot_id:string;summary:string;mode:string;ai_status?:string;limitations:string[];recommendations:Array<{property_id:string;suitability_reason:string;strengths:Array<{text:string;evidence_refs:string[]}>;tradeoffs:Array<{text:string;evidence_refs:string[]}>;unknowns:Array<{text:string;evidence_refs:string[]}>}>};
export type Measurement = {evaluation_request_id:string;freeze_at:string|null;snapshot_id:string;top_k_snapshot:Array<{property_id:string;property:Partial<PropertyListing>}>};
export async function api<T>(path:string, init?:RequestInit):Promise<T> {
  const response=await fetch(`/api${path}`,{...init,headers:{'Content-Type':'application/json',...init?.headers}});
  if(!response.ok) {const body=await response.json().catch(()=>({detail:'خطا در ارتباط با سرور'}));throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));}
  return response.json();
}
export const post=(body:unknown):RequestInit=>({method:'POST',body:JSON.stringify(body)});
export const digits=(value:number|string|null|undefined)=>value==null?'نامعلوم':new Intl.NumberFormat('fa-IR').format(Number(value));
export const money=(value:number|null)=>value===null?'نامعلوم':`${digits(value)} تومان`;
export const duration=(seconds:number|null)=>seconds===null?'نامعلوم':`${digits(Math.round(seconds/60))} دقیقه`;
export const featureId=(f:Boundary)=>String(f.id??f.properties.id);
export const normalize=(value:string)=>value.normalize('NFKC').replace(/[يى]/g,'ی').replace(/ك/g,'ک').replace(/\u200c/g,' ').replace(/[۰-۹]/g,d=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d))).replace(/[٠-٩]/g,d=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(d))).toLowerCase();
let cachedInventory:Inventory|null=null;
let inventoryTag:string|null=null;
export async function loadInventory():Promise<Inventory> {
  const response=await fetch('/api/inventory',{headers:inventoryTag?{'If-None-Match':inventoryTag}:{}});
  if(response.status===304&&cachedInventory) return cachedInventory;
  if(!response.ok) throw new Error('دریافت آگهی‌ها ممکن نشد؛ دوباره تلاش کنید.');
  cachedInventory=await response.json() as Inventory;inventoryTag=response.headers.get('ETag');return cachedInventory;
}
export function memberships(longitude:number,latitude:number,features:Boundary[]):string[] {return features.filter(f=>booleanPointInPolygon([longitude,latitude],f)).map(featureId);}
export function parseNumeric(value:string):number|null {
  if(!value.trim()) return null;
  const normalized=normalize(value).replace(/[,٬]/g,'').replace('٫','.');
  const number=Number(normalized);if(!Number.isFinite(number)||number<0) throw new Error('عدد نامعتبر است');return number;
}
