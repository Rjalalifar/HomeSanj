"""Use a stored synthetic property for the public walking contract."""
from pathlib import Path

path = Path("scripts/accessibility_probe_walk.py")
text = path.read_text(encoding="utf-8")
text = text.replace("import httpx\n", "import httpx\nfrom sqlalchemy import select\n")
text = text.replace("from backend.app.transit_stops import StopCatalog\n", "from backend.app.transit_stops import StopCatalog\nfrom backend.app.db import Database, Listing\nfrom backend.app.config import Settings\n")
text = text.replace('    contract = json.loads(Path("data/otp/contract-input.json").read_text(encoding="utf-8"))\n    origin = {key: contract["origin"][key] for key in ("latitude", "longitude")}\n', '''    database = Database(Settings.from_env().database_url)
    with database.session() as session:
        listing = session.scalar(select(Listing).where(Listing.is_synthetic.is_(True)).order_by(Listing.property_id).limit(1))
        if listing is None:
            raise ValueError("The existing synthetic property dataset is required")
        origin = {key: listing.payload[key] for key in ("latitude", "longitude")}
        property_id = listing.property_id
''')
text = text.replace('"point_source": "Existing public contract sample origin; nearest imported OTP quay coordinate.",', '"point_source": "Existing synthetic property origin; nearest imported OTP quay coordinate.", "property_id": property_id,')
path.write_text(text, encoding="utf-8")
