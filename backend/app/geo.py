"""Versioned Tehran boundary ingestion and authoritative spatial membership."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import httpx
from pyproj import Transformer
from shapely import STRtree, make_valid, normalize, to_wkb
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import transform, unary_union
from shapely.validation import explain_validity

from .normalize import normalize_text

DATASET_VERSION = 'tehran-2020-v1'
TRANSFORM_VERSION = 'geometry-v1'
SOURCES = {
 'neighborhood': 'https://raw.githubusercontent.com/mjalalimanesh/tehran-districts-neighborhoods-map-geojson/01028855efac0571a13f2a1ab8d29e6077825090/tehran_neighborhoods_376.geojson',
 'district': 'https://raw.githubusercontent.com/mjalalimanesh/tehran-districts-neighborhoods-map-geojson/5ec6a85f0419d177135babc3e43871eda4e185dc/tehran_districts_22.geojson',
}
TO_METRIC = Transformer.from_crs('EPSG:4326', 'EPSG:32639', always_xy=True).transform
TO_WGS84 = Transformer.from_crs('EPSG:32639', 'EPSG:4326', always_xy=True).transform


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def geometry_hash(geometry):
    return hashlib.sha256(to_wkb(normalize(geometry), byte_order=1)).hexdigest()


def stable_id(source_type, district, name, geometry):
    identity = [source_type, str(district), normalize_text(name), geometry_hash(geometry)]
    return source_type + '_' + hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]


def polygonal(geometry):
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = []
        for part in geometry.geoms:
            if isinstance(part, Polygon):
                polygons.append(part)
            elif isinstance(part, MultiPolygon):
                polygons.extend(part.geoms)
        return unary_union(polygons) if polygons else Polygon()
    raise ValueError('Boundary must contain Polygon or MultiPolygon')


def convert_feature(feature, source_type):
    props = dict(feature.get('properties') or {})
    original = shape(feature['geometry'])
    prepared = bool(props.get('id') or props.get('neighborhood_id') or props.get('district_id') or props.get('name_fa') or props.get('provenance'))
    district = props.get('district_no', props.get('district' if source_type == 'neighborhood' else 'area'))
    if district is None:
        raise ValueError('Boundary is missing district attribution')
    district = int(normalize_text(str(district)))
    name = str(props.get('name_fa') or props.get('name') or f'منطقه {district}')
    identifier = str(props.get('id') or props.get('neighborhood_id') or props.get('district_id') or (feature.get('id') if prepared else '') or stable_id(source_type, district, name, original))
    flags = list(props.get('quality_flags') or [])
    valid = polygonal(make_valid(original)) if not original.is_valid else original
    if valid.is_empty or not valid.is_valid or valid.area <= 0:
        raise ValueError(f'Unsampleable boundary: {identifier}')
    repair = None
    if not original.is_valid:
        flags.append('geometry_repaired')
        repair = {'id': identifier, 'method': 'shapely.make_valid; polygonal components only',
                  'reason': explain_validity(original), 'original_geometry': mapping(original),
                  'original_hash': geometry_hash(original), 'valid_hash': geometry_hash(valid),
                  'area_before_m2': transform(TO_METRIC, original).area, 'area_after_m2': transform(TO_METRIC, valid).area}
    props.update(id=identifier, name_fa=name, name_normalized=normalize_text(name), district_no=district,
                 quality_flags=sorted(set(flags)), geometry_hash=geometry_hash(valid))
    props.setdefault('source_type', source_type)
    props.setdefault('provenance', {'source_url': SOURCES[source_type], 'transform_version': TRANSFORM_VERSION,
                                    'source_geometry_hash': geometry_hash(original), 'source_district_assignment_verified': False})
    return {'type': 'Feature', 'id': identifier, 'properties': props, 'geometry': mapping(valid)}, repair


def validate_layers(neighborhoods, districts):
    ng = [transform(TO_METRIC, shape(f['geometry'])) for f in neighborhoods]
    dg = {f['properties']['district_no']: transform(TO_METRIC, shape(f['geometry'])) for f in districts}
    tree = STRtree(ng)
    overlaps, outside = [], []
    for i, geometry in enumerate(ng):
        for j in tree.query(geometry, predicate='intersects'):
            j = int(j)
            if j <= i:
                continue
            area = geometry.intersection(ng[j]).area
            if area > 1:
                overlaps.append({'a': neighborhoods[i]['id'], 'b': neighborhoods[j]['id'], 'area_m2': area})
                for index in (i, j):
                    flags = neighborhoods[index]['properties']['quality_flags']
                    if 'overlapping_neighborhood' not in flags:
                        flags.append('overlapping_neighborhood')
        assigned = neighborhoods[i]['properties']['district_no']
        if assigned not in dg:
            fraction = 1.0
        else:
            fraction = geometry.difference(dg[assigned]).area / geometry.area
        if fraction > 0.01:
            outside.append({'id': neighborhoods[i]['id'], 'assigned_district_no': assigned, 'outside_fraction': fraction})
            neighborhoods[i]['properties']['quality_flags'].append('source_district_mismatch')
    return {'neighborhood_count': len(neighborhoods), 'district_count': len(districts),
            'overlap_pairs_over_1m2': len(overlaps), 'outside_assigned_district_over_1pct': len(outside),
            'outside_assigned_district_over_50pct': sum(x['outside_fraction'] > .5 for x in outside),
            'overlaps': overlaps, 'district_mismatches': outside, 'metric_crs': 'EPSG:32639',
            'source_assignments_changed': False, 'full_city_coverage_verified': False}


def prepare(data_dir='data'):
    target = Path(data_dir)
    target.mkdir(parents=True, exist_ok=True)
    raw_dir = target / 'raw'
    raw_dir.mkdir(exist_ok=True)
    prepared_paths = [target / 'tehran-neighborhoods-377.geojson', target / 'tehran-districts-22.geojson']
    manifest_path = target / 'source-manifest.json'
    if all(path.exists() for path in prepared_paths) and manifest_path.exists():
        # Existing prepared IDs and provenance are never replaced by a new transform.
        GeometryStore(target)
        return json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    layers, repairs, files = {}, [], []
    for source_type, output in zip(('neighborhood', 'district'), prepared_paths):
        raw_path = raw_dir / f'{source_type}.geojson'
        if output.exists():
            input_path = output
        else:
            if not raw_path.exists():
                response = httpx.get(SOURCES[source_type], timeout=60, follow_redirects=True)
                response.raise_for_status()
                raw_path.write_bytes(response.content)
            input_path = raw_path
        content = input_path.read_bytes()
        collection = json.loads(content.decode('utf-8-sig'))
        features = []
        for feature in collection['features']:
            converted, repair = convert_feature(feature, source_type)
            features.append(converted)
            if repair:
                repairs.append(repair)
        layers[source_type] = features
        files.append({'type': source_type, 'url': SOURCES[source_type], 'sha256': hashlib.sha256(content).hexdigest(),
                      'input_path': str(input_path), 'output_path': str(output), 'feature_count': len(features)})
    report = validate_layers(layers['neighborhood'], layers['district'])
    report.update(repair_count=len(repairs), repairs=repairs, transform_version=TRANSFORM_VERSION)
    for name, output in zip(('neighborhood', 'district'), prepared_paths):
        dump(output, {'type': 'FeatureCollection', 'features': layers[name]})
    manifest = {'dataset_version': DATASET_VERSION, 'transform_version': TRANSFORM_VERSION, 'files': files,
        'source_last_file_commits': 'November 2020', 'boundary_validity_date': None,
        'license_status': 'No explicit data license identified in reviewed upstream repository',
        'neighborhood_crs': 'CRS84 declared in source', 'district_crs': 'WGS84 inferred from coordinates and colocation; metadata empty',
        'output_coordinate_order': '[longitude, latitude]', 'district_no_is_source_attribution': True,
        'full_city_coverage_verified': False, 'fresh_osm_extraction': False,
        'osm_tiles_independent': True, 'prepared_reference_statistics': {'repairs': 2, 'overlap_pairs_over_1m2': 120,
        'outside_assigned_district_over_1pct': 108, 'outside_assigned_district_over_50pct': 11}}
    dump(manifest_path, manifest)
    dump(target / 'validation-report.json', report)
    with (target / 'neighborhood-index.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['id', 'name_fa', 'name_normalized', 'district_no', 'quality_flags'])
        writer.writeheader()
        for feature in layers['neighborhood']:
            props = feature['properties']
            writer.writerow({key: json.dumps(props[key], ensure_ascii=False) if key == 'quality_flags' else props[key] for key in writer.fieldnames})
    return manifest


class GeometryStore:
    def __init__(self, data_dir='data', *, neighborhoods=None, districts=None, dataset_version=None):
        self.data_dir = Path(data_dir)
        if neighborhoods is None:
            neighborhoods = json.loads((self.data_dir / 'tehran-neighborhoods-377.geojson').read_text(encoding='utf-8-sig'))['features']
        if districts is None:
            districts = json.loads((self.data_dir / 'tehran-districts-22.geojson').read_text(encoding='utf-8-sig'))['features']
        if dataset_version is None:
            manifest = json.loads((self.data_dir / 'source-manifest.json').read_text(encoding='utf-8-sig'))
            dataset_version = manifest['dataset_version']
        self.dataset_version = dataset_version
        for feature in neighborhoods + districts:
            props = feature.get('properties') or {}
            identifier = feature.get('id') or props.get('id') or props.get('neighborhood_id') or props.get('district_id')
            if identifier is None:
                raise ValueError('Prepared feature has no stable identifier')
            feature['id'] = str(identifier)
            props.setdefault('id', str(identifier))
            feature['properties'] = props
        self.neighborhoods, self.districts = neighborhoods, districts
        self._ng = [shape(f['geometry']) for f in neighborhoods]
        self._dg = [shape(f['geometry']) for f in districts]
        for geometry in self._ng + self._dg:
            if not isinstance(geometry, (Polygon, MultiPolygon)) or not geometry.is_valid or geometry.is_empty:
                raise ValueError('Prepared geometry must be a valid nonempty Polygon or MultiPolygon')
        self._ntree, self._dtree = STRtree(self._ng), STRtree(self._dg)
        self._features = {str(f['id']): f for f in neighborhoods + districts}
        if len(self._features) != len(neighborhoods) + len(districts):
            raise ValueError('Boundary IDs must be unique')

    def feature(self, identifier):
        return self._features[identifier]

    def neighborhood_memberships(self, longitude, latitude):
        return self._memberships(longitude, latitude, self._ntree, self.neighborhoods)

    def district_memberships(self, longitude, latitude):
        return self._memberships(longitude, latitude, self._dtree, self.districts)

    @staticmethod
    def _memberships(longitude, latitude, tree, features):
        return sorted(str(features[int(i)]['id']) for i in tree.query(Point(longitude, latitude), predicate='intersects'))

    def validate_selections(self, neighborhood_ids, district_ids):
        if set(neighborhood_ids) - {f['id'] for f in self.neighborhoods} or set(district_ids) - {f['id'] for f in self.districts}:
            raise ValueError('Unknown boundary ID')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()
    result = prepare(args.data_dir)
    print(json.dumps({'dataset_version': result['dataset_version'], 'feature_counts': {f['type']: f['feature_count'] for f in result.get('files', [])}}))
