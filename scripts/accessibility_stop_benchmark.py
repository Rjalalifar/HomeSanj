"""Measure nearest-stop lookup over the existing demo properties without routing."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import Settings
from backend.app.db import Database, Listing
from backend.app.transit_stops import StopCatalog


started = perf_counter()
catalogue = StopCatalog()
build_seconds = perf_counter() - started
database = Database(Settings.from_env().database_url)
with database.session() as session:
    listings = session.scalars(select(Listing).where(Listing.is_synthetic.is_(True)).order_by(Listing.property_id)).all()
started = perf_counter()
found = 0
for listing in listings:
    found += bool(catalogue.nearest(listing.payload["latitude"], listing.payload["longitude"]))
elapsed = perf_counter() - started
report = {"status": "pass" if found == len(listings) and found > 0 else "fail", "measured_at": datetime.now(timezone.utc).isoformat(),
          "stop_dataset_version": catalogue.version, "stop_count": len(catalogue.stops), "property_count": len(listings),
          "properties_with_nearest_stop": found, "index_build_seconds": build_seconds,
          "all_properties_nearest_stop_seconds": elapsed, "mean_lookup_milliseconds": elapsed * 1000 / len(listings) if listings else None,
          "routing_requests": 0, "method": "Exact spherical 3D k-d tree; final distances use Haversine.",
          "scope": "Single local-process catalogue load and lookup pass; not an end-to-end routing latency benchmark."}
Path("data/otp/stops-performance-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
