import { useMemo } from 'react';
import { CircleMarker, GeoJSON, MapContainer, Marker, Popup, TileLayer, useMapEvents } from 'react-leaflet';
import { divIcon } from 'leaflet';
import type { LatLng } from 'leaflet';
import type { FeatureCollection } from 'geojson';
import type { Boundary, ResultRow } from './api';
import { money, memberships } from './api';

export const series = {
  demo_a:{label:'گروه الف',color:'#177b67',symbol:'●'},
  demo_b:{label:'گروه ب',color:'#cc822c',symbol:'◆'},
  demo_c:{label:'گروه ج',color:'#7567ab',symbol:'■'},
};
const icons=Object.fromEntries(Object.entries(series).map(([id,s])=>[id,divIcon({className:'listing-pin',html:`<span style="color:${s.color}">${s.symbol}</span>`,iconSize:[20,20],iconAnchor:[10,10]})]));
function ClickHandler({choose,onChoose}:{choose:boolean;onChoose:(point:LatLng)=>void}) {
  useMapEvents({click:event=>{if(choose) onChoose(event.latlng);}});
  return null;
}
export default function SearchMap({neighborhoods,districts,rows,selected,selectedDistricts,choose,onChoose,destination,showBoundaries}: {
  neighborhoods:Boundary[];districts:Boundary[];rows:ResultRow[];selected:string[];selectedDistricts:string[];
  choose:boolean;onChoose:(point:{latitude:number;longitude:number;memberships:string[]})=>void;
  destination:{latitude:number;longitude:number}|null;showBoundaries:boolean;
}) {
  const visible=useMemo(()=>neighborhoods.filter(f=>selected.includes(String(f.id??f.properties.id))),[neighborhoods,selected]);
  const visibleDistricts=useMemo(()=>districts.filter(f=>selectedDistricts.includes(String(f.id??f.properties.id))),[districts,selectedDistricts]);
  return <div className={`map-shell ${choose?'choosing':''}`}>
    <MapContainer center={[35.71,51.40]} zoom={11} scrollWheelZoom className="map" preferCanvas>
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"/>
      <ClickHandler choose={choose} onChoose={p=>onChoose({latitude:p.lat,longitude:p.lng,memberships:memberships(p.lng,p.lat,neighborhoods)})}/>
      {showBoundaries&&<GeoJSON key="all-neighborhoods" data={{type:'FeatureCollection',features:neighborhoods} as FeatureCollection} style={{color:'#567467',weight:0.5,fillOpacity:0.025}}/>}
      <GeoJSON key={selected.join(',')} data={{type:'FeatureCollection',features:visible} as FeatureCollection} style={{color:'#14785d',weight:2,fillOpacity:0.16}}/>
      <GeoJSON key={`d-${selectedDistricts.join(',')}`} data={{type:'FeatureCollection',features:visibleDistricts} as FeatureCollection} style={{color:'#bc8a43',weight:3,fillOpacity:0.05,dashArray:'5 5'}}/>
      {rows.slice(0,200).map(({property:p})=>p.latitude!==null&&p.longitude!==null&&<Marker key={p.property_id} position={[p.latitude,p.longitude]} icon={icons[p.series_id??'demo_a']??icons.demo_a}>
        <Popup><strong>{p.title_fa}</strong><p>{p.is_synthetic?'آگهی نمایشی':'آگهی واردشده'}</p><p>اجاره: {money(p.monthly_rent_toman)}</p></Popup>
      </Marker>)}
      {destination&&<CircleMarker center={[destination.latitude,destination.longitude]} radius={10} pathOptions={{color:'#fff',weight:3,fillColor:'#e15a3e',fillOpacity:1}}><Popup>مقصد تأییدشده</Popup></CircleMarker>}
    </MapContainer>
    <div className="map-legend">{Object.entries(series).map(([id,s])=><span key={id}><b style={{color:s.color}}>{s.symbol}</b> {s.label}</span>)}<small>گروه داده؛ بدون معنای قیمت یا دسترسی</small></div>
    {choose&&<div className="map-hint">روی مقصد کلیک کنید و سپس آن را تأیید کنید.</div>}
  </div>;
}
