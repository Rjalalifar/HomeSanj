import { useEffect, useMemo, useState } from 'react';
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import type { GeoJsonObject } from 'geojson';
import type { Destination, Itinerary } from './contracts.generated';
import { featureId, memberships, money } from './api';
import type { Boundary, ResultRow } from './api';

type Props = {
  neighborhoods: Boundary[]; districts: Boundary[]; results: ResultRow[];
  selected: string[]; selectedDistricts: string[]; destination: Destination | null;
  chooseDestination: boolean; onDestination: (latitude: number, longitude: number, memberships: string[]) => void;
  onToggleNeighborhood: (id: string) => void; onSelectProperty: (id: string) => void;
  selectedPropertyId: string | null; route: Itinerary | null;
};
const colors: Record<string, string> = { demo_a: '#c43b39', demo_b: '#2364aa', demo_c: '#17836c' };

function Interactions({ props, onAmbiguous }: { props: Props; onAmbiguous: (ids: string[]) => void }) {
  const map = useMapEvents({ click(event) {
    const ids = memberships(event.latlng.lng, event.latlng.lat, props.neighborhoods);
    if (props.chooseDestination) props.onDestination(event.latlng.lat, event.latlng.lng, ids);
    else if (ids.length === 1) props.onToggleNeighborhood(ids[0]);
    else onAmbiguous(ids);
  } });
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  useEffect(() => {
    const property = props.results.find(r => r.property.property_id === props.selectedPropertyId)?.property;
    if (property?.latitude != null && property.longitude != null && !map.getBounds().contains([property.latitude, property.longitude])) map.panTo([property.latitude, property.longitude]);
  }, [props.selectedPropertyId, map]);
  return null;
}

function Boundaries({ features, selected, district = false }: { features: Boundary[]; selected: string[]; district?: boolean }) {
  const data = useMemo(() => ({ type: 'FeatureCollection', features }) as GeoJsonObject, [features]);
  return <GeoJSON key={`${district}:${selected.join(',')}`} data={data} interactive={false} style={feature => {
    const active = selected.includes(String(feature?.id ?? feature?.properties.id));
    return { color: district ? '#755b93' : active ? '#cc3030' : '#718197', weight: active ? 2.5 : district ? 1.5 : .7, opacity: active ? .9 : .45, fillOpacity: active ? .15 : .015, dashArray: district ? '5 4' : undefined };
  }} />;
}

function RouteShape({ itinerary }: { itinerary: Itinerary | null }) {
  const map = useMap();
  useEffect(() => {
    if (!itinerary?.geometry) return;
    try {
      const bounds = L.geoJSON(itinerary.geometry as unknown as GeoJsonObject).getBounds();
      if (bounds.isValid()) map.fitBounds(bounds, { padding: [25, 25], maxZoom: 15 });
    } catch { /* Invalid recorded geometry never replaces the map with an invented route. */ }
  }, [itinerary?.itinerary_id, map]);
  if (!itinerary?.geometry) return null;
  const legs = itinerary.legs.filter(leg => leg.geometry && typeof leg.geometry === 'object');
  if (legs.length) return <>{legs.map((leg, index) => <GeoJSON key={`${itinerary.itinerary_id}-${index}`} data={leg.geometry as GeoJsonObject} interactive={false} style={{color:leg.mode === 'WALK' ? '#42687b' : '#a42b78',weight:leg.mode === 'WALK' ? 4 : 5,dashArray:leg.mode === 'WALK' ? '6 5' : undefined,opacity:.9}} />)}</>;
  return <GeoJSON key={itinerary.itinerary_id} data={itinerary.geometry as unknown as GeoJsonObject} interactive={false} style={{ color: '#a42b78', weight: 5, opacity: .85 }} />;
}

export default function PhaseTwoMap(props: Props) {
  const [tileFailed, setTileFailed] = useState(false);
  const [showDistricts, setShowDistricts] = useState(false);
  const environment = (import.meta as ImportMeta & {env: Record<string, string>}).env;
  const [ambiguous, setAmbiguous] = useState<string[]>([]);
  const canvas = useMemo(() => L.canvas({ padding: .3 }), []);
  return <div className={`map-shell ${props.chooseDestination ? 'choosing' : ''}`}>
    {tileFailed && <p className="tile-warning" role="status">کاشی پس‌زمینه بارگیری نشد؛ مرزها، نقاط و فهرست همچنان قابل استفاده‌اند.</p>}
    <MapContainer center={[35.7107, 51.3978]} zoom={11} preferCanvas renderer={canvas} scrollWheelZoom={false}>
      <TileLayer url={environment.VITE_MAP_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png"} attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' eventHandlers={{ tileerror: () => setTileFailed(true) }} />
      <Boundaries features={props.neighborhoods} selected={props.selected} />
      {(showDistricts || props.selectedDistricts.length > 0) && <Boundaries features={props.districts} selected={props.selectedDistricts} district />}
      <Interactions props={props} onAmbiguous={setAmbiguous} />
      {props.results.filter(row => row.property.latitude !== null && row.property.longitude !== null).map(row => {
        const p = row.property, active = props.selectedPropertyId === p.property_id;
        return <CircleMarker key={p.property_id} center={[p.latitude!, p.longitude!]} radius={active ? 10 : 6} bubblingMouseEvents={false} pathOptions={{ color: colors[p.series_id ?? ''] ?? '#64748b', fillColor: colors[p.series_id ?? ''] ?? '#64748b', fillOpacity: .9, weight: active ? 4 : 1, dashArray: p.series_id === 'demo_b' ? '2 2' : undefined }} eventHandlers={{ click: event => { L.DomEvent.stopPropagation(event.originalEvent); if (props.chooseDestination) props.onDestination(p.latitude!, p.longitude!, memberships(p.longitude!, p.latitude!, props.neighborhoods)); else props.onSelectProperty(p.property_id); } }}>
          <Popup><div dir="rtl"><strong>{p.title_fa}</strong><p>{p.is_synthetic ? 'آگهی نمایشی' : 'آگهی واردشده'}</p><p>{money(p.monthly_rent_toman)}</p><button onClick={() => props.onSelectProperty(p.property_id)}>نمایش در فهرست</button></div></Popup>
        </CircleMarker>;
      })}
      {props.destination && <CircleMarker center={[props.destination.latitude, props.destination.longitude]} radius={10} bubblingMouseEvents={false} pathOptions={{ color: '#111827', fillColor: '#ffd24a', fillOpacity: 1, weight: 3 }}><Popup>{props.destination.label}</Popup></CircleMarker>}
      <RouteShape itinerary={props.route} />
    </MapContainer>
    {!props.chooseDestination && ambiguous.length > 1 && <div className="overlap-choice"><strong>این نقطه در چند محله است؛ انتخاب کنید:</strong>{ambiguous.map(id => <button key={id} onClick={() => { props.onToggleNeighborhood(id); setAmbiguous([]); }}>{props.neighborhoods.find(n => featureId(n) === id)?.properties.name_fa}</button>)}<button onClick={() => setAmbiguous([])}>بستن</button></div>}
    <label className="district-overlay"><input type="checkbox" checked={showDistricts} onChange={e => setShowDistricts(e.target.checked)} /> نمایش مرز مناطق</label><div className="map-legend"><span className="demo_a">● گروه الف</span><span className="demo_b">■ گروه ب</span><span className="demo_c">▲ گروه پ</span><small>سه گروه داده، بدون معنای قیمت، کیفیت یا دسترسی</small></div>
  </div>;
}
