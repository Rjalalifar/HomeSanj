from copy import deepcopy

from backend.app.config import Settings
from backend.app.contracts import SearchInput, SearchState
from backend.app.db import Database, Listing
from backend.app.search import create_search, read_search
from tests.test_search import TinyGeo, listing


def test_current_snapshot_rank_factors_survive_inventory_and_paging_changes(tmp_path):
    db = Database(f'sqlite:///{tmp_path / "replay.sqlite3"}')
    db.migrate()
    db.insert_listings([listing(f'p{i}', .5, 10 + i, True) for i in range(8)])
    state = SearchState(dataset_version='test', soft_preferences=['parking'])
    rid = create_search(db, TinyGeo(), SearchInput(state=state), Settings(), False)
    original = read_search(db, rid)
    partial = read_search(db, rid, limit=1)
    assert original['results'][0] == partial['results'][0]
    with db.session.begin() as session:
        changed = session.get(Listing, 'p0')
        changed.payload = {**changed.payload, 'monthly_rent_toman': 99999999, 'parking': False}
    assert read_search(db, rid)['results'] == original['results']
    assert original['ranking_policy']['normalization'].startswith('min(value')
    assert original['ranking_policy']['mode'] == 'finance_only'
