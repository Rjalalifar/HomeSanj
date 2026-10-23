"""Compare direct local HTTP with inherited proxy settings without printing secrets."""
import json
import httpx

for port in (8000, 8821, 6333):
    for trust in (True, False):
        try:
            response = httpx.get(f'http://127.0.0.1:{port}/', timeout=5, trust_env=trust)
            print(json.dumps({'port': port, 'trust_env': trust, 'status': response.status_code}))
        except httpx.HTTPError as exc:
            print(json.dumps({'port': port, 'trust_env': trust, 'error': type(exc).__name__}))
