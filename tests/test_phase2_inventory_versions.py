from copy import deepcopy
from shapely.geometry import box, mapping

from backend.app.catalog import Catalog
from backend.app.db import Database
from tests.test_search import TinyGeo, listing


def test_boundary_revision_changes_inventory_etag_and_assignments(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "versions.sqlite3"}')
    db.migrate()
    db.insert_listings([listing('p1', .5, 10, True)])
    original = Catalog(db, TinyGeo())
    original.refresh()
    changed = TinyGeo()
    changed.districts = deepcopy(changed.districts)
    changed.districts[0]['geometry'] = mapping(box(10, 10, 11, 11))
    updated = Catalog(db, changed)
    updated.refresh()
    assert updated.public['properties'][0]['district_ids'] == []
    assert original.public['properties'][0]['district_ids'] == ['d1']
    assert updated.version != original.version
