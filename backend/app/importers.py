"""Two offline input contracts. Importing is not a live source connection."""
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from .contracts import PropertyListing
from .normalize import normalize_text, parse_bool, parse_money, parse_number

IMPORTER_VERSION = 'listing-import-1'


def _url(value):
    if not value:
        return None
    if urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc:
        raise ValueError('Source URL must be an actual HTTP(S) URL or null')
    return value


def import_listings(path: str, kind: str, dataset_version: str, geo=None, synthetic=True):
    """Return normalized listings and rejected rows; never overwrite stored listings."""
    with open(path, encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle)) if kind == 'csv_a' else json.load(handle)['ads']
    groups, rejected = {}, []
    for index, raw in enumerate(rows):
        try:
            if kind == 'csv_a':
                source, source_id = 'fixture_csv_a', str(raw['id'])
                data = dict(title=raw.get('title'), lat=raw.get('lat'), lon=raw.get('lng'),
                            deposit=raw.get('deposit'), rent=raw.get('rent'), unit=raw.get('currency') or 'toman',
                            area=raw.get('area'), rooms=raw.get('rooms'), parking=raw.get('parking'),
                            elevator=raw.get('elevator'), published=raw.get('published_at'), url=raw.get('url'))
            elif kind == 'json_b':
                source, source_id = 'fixture_json_b', str(raw['listing_code'])
                money, location, facts = raw.get('price', {}), raw.get('location', {}), raw.get('features', {})
                data = dict(title=raw.get('headline'), lat=location.get('latitude'), lon=location.get('longitude'),
                            deposit=money.get('bond'), rent=money.get('per_month'), unit=money.get('unit', 'rial'),
                            area=facts.get('square_meters'), rooms=facts.get('bedrooms'),
                            parking=facts.get('car_space'), elevator=facts.get('lift'),
                            published=raw.get('posted'), url=raw.get('link'))
            else:
                raise ValueError('Unknown input contract')
            if not source_id.strip():
                raise ValueError('Missing source identifier')
            lat, lon = parse_number(data['lat']), parse_number(data['lon'])
            nids = geo.neighborhood_memberships(lon, lat) if geo and lat is not None and lon is not None else []
            dids = geo.district_memberships(lon, lat) if geo and lat is not None and lon is not None else []
            membership = lambda ids: ('unique' if len(ids) == 1 else 'ambiguous' if ids else 'outside') if geo and lat is not None else 'unknown'
            item = PropertyListing(
                property_id='import_' + hashlib.sha256(f'{source}:{source_id}'.encode()).hexdigest()[:24],
                neighborhood_id=nids[0] if len(nids) == 1 else None, neighborhood_ids=nids,
                neighborhood_membership_status=membership(nids), district_ids=dids,
                district_membership_status=membership(dids), title_fa=data['title'] or 'آگهی بدون عنوان',
                latitude=lat, longitude=lon, deposit_toman=parse_money(data['deposit'], data['unit']),
                monthly_rent_toman=parse_money(data['rent'], data['unit']), area_m2=parse_number(data['area']),
                bedrooms=parse_number(data['rooms'], integer=True), parking=parse_bool(data['parking']),
                elevator=parse_bool(data['elevator']), location_accuracy='source_reported' if lat is not None else 'unknown',
                source_records=[{'source': source, 'source_id': source_id, 'url': _url(data['url']),
                                 'raw': raw, 'published_at': data['published'] or None}],
                published_at=data['published'] or None, collected_at=None,
                is_synthetic=synthetic, dataset_version=dataset_version,
            ).model_dump(mode='json')
            key = (source, source_id)
            if key in groups:
                previous = groups[key]
                records = previous['source_records'] + item['source_records']
                # Identical source and source ID are strong evidence; proximity or title are not.
                chosen = item if (item['published_at'] or '') > (previous['published_at'] or '') else previous
                chosen['source_records'] = records
                chosen['quality_flags'] = sorted(set(chosen['quality_flags'] + ['duplicate_source_id', 'source_values_preserved']))
                groups[key] = chosen
            else:
                groups[key] = item
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append({'row': index + 1, 'reason': str(exc), 'raw': raw})
    return list(groups.values()), {'input_count': len(rows), 'output_count': len(groups), 'rejected': rejected,
                                   'importer_version': IMPORTER_VERSION, 'live_sources_connected': 0}
