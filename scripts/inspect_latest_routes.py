"""Print only status and API error evidence for the latest local acceptance request."""
import json
from sqlalchemy import select
from backend.app.config import Settings
from backend.app.db import Database, Evaluation, SearchRequest

db = Database(Settings.from_env().database_url)
with db.session() as session:
    req = session.scalar(select(SearchRequest).where(SearchRequest.candidate_count == 3).order_by(SearchRequest.created_at.desc()).limit(1))
    for row in session.scalars(select(Evaluation).where(Evaluation.request_id == req.request_id)):
        print(json.dumps({key: row.result.get(key) for key in ('status', 'http_status', 'routing_errors', 'invalid_itineraries', 'itinerary_evaluations')}, ensure_ascii=True))
