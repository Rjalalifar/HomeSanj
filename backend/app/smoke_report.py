"""Write a truthful provider report without issuing a paid request."""
import json
from pathlib import Path

from .config import Settings
from .db import Database, utcnow
from .llm import AvalAIProvider


def main():
    settings = Settings.from_env()
    database = Database(settings.database_url)
    database.migrate()
    provider = AvalAIProvider(database)
    result = {'status': 'NOT RUN', 'checked_at': utcnow(), 'paid_requests': 0,
        'credentials_configured': bool(provider.key),
        'reason': 'Real account credentials and explicit paid smoke enablement are required; no endpoint/model success claimed.',
        'requested_models': provider.models, 'resolved_verified_model': None,
        'json_schema_capability': 'not_verified',
        'command': '.\\.venv\\Scripts\\python.exe -m backend.app.cli avalai-smoke --allow-paid --max-requests 1'}
    Path('docs/phase-2-avalai-smoke-report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
