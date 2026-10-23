"""Deterministic metric-area sampling with bounded overlap rejection."""
import hashlib
import random
from datetime import datetime, timedelta, timezone

from shapely.geometry import MultiPolygon, Point, shape
from shapely.ops import transform

from .geo import TO_METRIC, TO_WGS84

SERIES = ('demo_a', 'demo_b', 'demo_c')
MAX_ATTEMPTS_PER_POINT = 1000
SEED_VERSION = 'seed-v1'


def sample_metric_point(geometry, rng, max_attempts=1000):
    projected = transform(TO_METRIC, geometry)
    parts = list(projected.geoms) if isinstance(projected, MultiPolygon) else [projected]
    parts = [part for part in parts if part.area > 0]
    if not parts:
        return None
    # Choose the component once by metric area, then sample uniformly inside it.
    part = rng.choices(parts, weights=[part.area for part in parts], k=1)[0]
    left, bottom, right, top = part.bounds
    for _ in range(max_attempts):
        point = Point(rng.uniform(left, right), rng.uniform(bottom, top))
        if part.contains(point):
            return transform(TO_WGS84, point)
    return None


def generate_listings(store, seed: int, dataset_version: str, points_per_series_per_neighborhood=5, limit_neighborhoods=None):
    if dataset_version != store.dataset_version:
        raise ValueError('Seed dataset version does not match the boundary data')
    if points_per_series_per_neighborhood < 1:
        raise ValueError('Positive points per series required')
    features = sorted(store.neighborhoods, key=lambda feature: feature['id'])
    if limit_neighborhoods is not None:
        features = features[:limit_neighborhoods]
    listings, shortages, attempts, overlap_rejections = [], [], 0, 0
    counts = {series: 0 for series in SERIES}
    for feature in features:
        identifier = feature['id']
        geometry = shape(feature['geometry'])
        for series in SERIES:
            produced = 0
            for slot in range(points_per_series_per_neighborhood):
                identity = f'{SEED_VERSION}:{dataset_version}:{seed}:{identifier}:{series}:{slot}'
                digest = hashlib.sha256(identity.encode()).hexdigest()
                rng = random.Random(int(digest, 16))
                point = None
                for _ in range(MAX_ATTEMPTS_PER_POINT):
                    attempts += 1
                    proposed = sample_metric_point(geometry, rng, max_attempts=100)
                    if proposed is None or not geometry.contains(proposed):
                        continue
                    memberships = store.neighborhood_memberships(proposed.x, proposed.y)
                    if memberships != [identifier]:
                        overlap_rejections += 1
                        continue
                    point = proposed
                    break
                if point is None:
                    continue
                districts = store.district_memberships(point.x, point.y)
                published = datetime(2020, 11, 1, tzinfo=timezone.utc) + timedelta(days=rng.randrange(30))
                area = rng.randrange(35, 181, 5)
                deposit = rng.randrange(1, 31) * 100_000_000
                rent = rng.randrange(1, 41) * 1_000_000
                item = {'property_id': 'demo_' + digest[:24], 'series_id': series,
                    'neighborhood_id': identifier, 'neighborhood_ids': [identifier], 'neighborhood_membership_status': 'unique',
                    'district_ids': districts, 'district_membership_status': 'unique' if len(districts) == 1 else 'ambiguous' if districts else 'outside',
                    'title_fa': f'آگهی نمایشی آپارتمان {area} متری در {feature["properties"]["name_fa"]}',
                    'latitude': point.y, 'longitude': point.x, 'deposit_toman': deposit, 'monthly_rent_toman': rent,
                    'area_m2': area, 'bedrooms': rng.randrange(1, 5), 'parking': rng.choice([True, False, None]),
                    'elevator': rng.choice([True, False, None]), 'location_accuracy': 'synthetic_exact',
                    'source_records': [{'source': 'deterministic_demo_generator', 'source_id': digest, 'url': None,
                        'raw': {'seed': seed, 'dataset_version': dataset_version, 'generator_version': SEED_VERSION,
                                'series': series, 'slot': slot, 'prices_are_synthetic': True},
                        'published_at': published.isoformat(), 'collected_at': None}],
                    'published_at': published.isoformat(), 'collected_at': None, 'is_synthetic': True,
                    'dataset_version': dataset_version, 'seed': seed, 'quality_flags': ['synthetic_price', 'synthetic_location', 'synthetic_publication_date']}
                listings.append(item)
                produced += 1
                counts[series] += 1
            if produced < points_per_series_per_neighborhood:
                shortages.append({'neighborhood_id': identifier, 'series_id': series, 'requested': points_per_series_per_neighborhood, 'generated': produced})
    report = {'seed': seed, 'dataset_version': dataset_version, 'generator_version': SEED_VERSION,
        'points_per_series_per_neighborhood': points_per_series_per_neighborhood,
        'neighborhood_count': len(features), 'expected_count': len(features) * 3 * points_per_series_per_neighborhood,
        'generated_count': len(listings), 'series_counts': counts, 'shortages': shortages,
        'attempts': attempts, 'overlap_rejections': overlap_rejections,
        'max_attempts_per_point': MAX_ATTEMPTS_PER_POINT, 'max_bbox_draws_per_candidate': 100, 'sampling_crs': 'EPSG:32639',
        'identity_hash': hashlib.sha256('\n'.join(item['property_id'] for item in listings).encode()).hexdigest()}
    return listings, report
