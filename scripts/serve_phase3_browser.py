"""Run a local isolated browser-test backend with copied synthetic canonical listings."""
import json
import os
from pathlib import Path
import secrets
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from backend.app.config import Settings
from backend.app.db import Database, Listing
from backend.app.geo import GeometryStore
from backend.app.catalog import Catalog
from backend.app.contracts import SearchState, SearchInput
from backend.app.search import create_search
from backend.app.review_workflow import acquire_batch
from backend.app.main import create_app
from backend.app.routing import OTPAdapter, OTPSettings

settings = Settings.from_env()
source = Database(settings.database_url)
with source.session() as session:
    listings = [row.payload for row in session.scalars(select(Listing).where(Listing.is_synthetic.is_(True)))]
root = Path('runtime/phase3-browser') / secrets.token_hex(6)
root.mkdir(parents=True)
database = Database('sqlite:///' + str(root / 'test.sqlite'))
database.migrate()
database.insert_listings(listings)
geo = GeometryStore(settings.data_dir)
catalog = Catalog(database, geo)
catalog.refresh()
state = SearchState(dataset_version=geo.dataset_version, selected_neighborhood_ids=[geo.neighborhoods[0]['properties']['neighborhood_id']] if 'neighborhood_id' in geo.neighborhoods[0]['properties'] else [])
rid = create_search(database, geo, SearchInput(state=state), settings, False, versions={'inventory': catalog.version, 'boundary_assignments': catalog.boundary_version}, catalog=catalog)
sample = acquire_batch(database, [rid], batch_size=4)
token = secrets.token_urlsafe(32)
os.environ['REVIEW_API_TOKEN'] = token
os.environ['REVIEW_ANNOTATION_SOURCE'] = 'automated_test'
os.environ['AI_JUDGE_ENABLED'] = 'false'
os.environ['AI_IMPROVEMENT_ENABLED'] = 'false'
os.environ['LLM_ENABLED'] = 'false'
Path('runtime/phase3-browser-config.json').write_text(json.dumps({'token': token, 'request_id': rid, 'samples': sample['sample_ids'], 'database': str(root / 'test.sqlite')}), encoding='utf-8')
live_accessibility = os.getenv('ACCESSIBILITY_BROWSER_LIVE_OTP') == 'true'
if live_accessibility:
    settings.batch_limit = 3
app = create_app(settings, database=database, geo=geo,
    adapter=OTPAdapter(OTPSettings.from_env() if live_accessibility else OTPSettings()))
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8001, log_level='warning')
