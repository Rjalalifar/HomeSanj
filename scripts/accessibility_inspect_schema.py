"""Print only the local OTP fields needed for stop and pedestrian discovery."""
import json
from pathlib import Path

schema = json.loads(Path("data/otp/introspection.json").read_text(encoding="utf-8"))["data"]["__schema"]
types = {item["name"]: item for item in schema["types"]}
for name in ("QueryType", "Query", "Quay", "StopPlace", "Line", "JourneyPattern", "Modes", "TransportMode", "StreetMode"):
    item = types.get(name)
    if item is None:
        continue
    fields = item.get("fields") or item.get("inputFields") or item.get("enumValues") or []
    if name in ("QueryType", "Query"):
        fields = [field for field in fields if field["name"] in ("quays", "stopPlaces", "lines", "trip", "serverInfo")]
    print(json.dumps({"name": name, "fields": fields}, ensure_ascii=True))
