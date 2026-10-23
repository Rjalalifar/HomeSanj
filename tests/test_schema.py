import json
from pathlib import Path
from backend.app.export_schema import Contracts, export_schema


def test_committed_schema_matches_canonical_models():
    assert json.loads(Path('shared/contracts.schema.json').read_text(encoding='utf-8')) == Contracts.model_json_schema()


def test_schema_generation_is_deterministic():
    before = Path('frontend/src/contracts.generated.ts').read_bytes()
    export_schema()
    assert Path('frontend/src/contracts.generated.ts').read_bytes() == before
