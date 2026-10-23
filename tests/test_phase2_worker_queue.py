from backend.app.catalog import SearchAnalysis
from backend.app.contracts import SearchInput
from backend.app.search import create_search
from backend.app.worker import RoutingWorker
from tests.test_search import TinyGeo
from tests.test_worker_api import setup, FakeOTP


def test_pending_semantic_job_cannot_block_normal_routing(tmp_path):
    db, settings, state = setup(tmp_path, count=1)
    advanced = create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    with db.session.begin() as session:
        session.add(SearchAnalysis(request_id=advanced, search_mode='advanced', status='pending', metadata_json={}, priority_ids=[]))
    normal = create_search(db, TinyGeo(), SearchInput(state=state), settings, True)
    assert RoutingWorker(db, FakeOTP(), settings).claim() == normal
