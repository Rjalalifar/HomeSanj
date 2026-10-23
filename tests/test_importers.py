from backend.app.importers import import_listings
from backend.app.db import Database, Listing


def test_importers_preserve_null_and_duplicate_source_prices():
    a, report = import_listings('tests/fixtures/listings-a.csv', 'csv_a', 'test')
    assert report['input_count'] == 4 and len(a) == 2 and len(report['rejected']) == 1
    assert a[0]['monthly_rent_toman'] == 13_000_000
    assert len(a[0]['source_records']) == 2
    assert a[1]['deposit_toman'] is None and a[1]['elevator'] is None
    b, report = import_listings('tests/fixtures/listings-b.json', 'json_b', 'test')
    assert len(b) == 2 and len(report['rejected']) == 1
    assert b[0]['monthly_rent_toman'] == 11_000_000
    assert len(b[0]['source_records']) == 2


def test_seed_insert_never_overwrites_existing_listing():
    db = Database('sqlite:///:memory:')
    db.migrate()
    items, _ = import_listings('tests/fixtures/listings-a.csv', 'csv_a', 'test')
    assert db.insert_listings(items)['inserted'] == 2
    items[0]['monthly_rent_toman'] = 1
    assert db.insert_listings(items)['skipped_existing'] == 2
    with db.session() as session:
        assert session.get(Listing, items[0]['property_id']).monthly_rent_toman == 13_000_000
