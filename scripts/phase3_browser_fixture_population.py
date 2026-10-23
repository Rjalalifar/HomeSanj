"""Reuse the full synthetic population for the unchanged Phase-2 neighborhood scenario."""
from pathlib import Path
p = Path('scripts/serve_phase3_browser.py')
s = p.read_text(encoding='utf-8').replace("Listing.is_synthetic.is_(True)).limit(30)", "Listing.is_synthetic.is_(True))")
s = s.replace("state = SearchState(dataset_version=geo.dataset_version)", "state = SearchState(dataset_version=geo.dataset_version, selected_neighborhood_ids=[geo.neighborhoods[0]['properties']['neighborhood_id']] if 'neighborhood_id' in geo.neighborhoods[0]['properties'] else [])")
p.write_text(s, encoding='utf-8')
