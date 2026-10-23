"""Discover the user's existing OTP API from the UI, then run explicit contracts."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import httpx

SCHEMA_QUERY = """query {
  __schema {
    queryType { name }
    types {
      kind name description
      fields(includeDeprecated: true) {
        name description
        args { name defaultValue type { kind name ofType { kind name ofType { kind name ofType { kind name } } } } }
        type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
      }
      inputFields { name description defaultValue type { kind name ofType { kind name ofType { kind name } } } }
      enumValues { name description }
    }
  }
}"""


async def discover(base_url="http://127.0.0.1:8821", output="data/otp"):
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    report = {
        "base_url": base_url, "root_reachable": False, "routing_api_verified": False,
        "fixture_mode": False, "contract_test_status": "not_run", "api_path": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
        try:
            root = await client.get(base_url + "/")
            report["root_status"] = root.status_code
            root.raise_for_status()
            report["root_reachable"] = True
            (target / "root.html").write_text(root.text, encoding="utf-8")
            scripts = re.findall(r'<script[^>]+src="([^"]+)"', root.text)
            report["ui_scripts"] = scripts
            discovered = set()
            for script in scripts[:3]:
                if not script.startswith("https://www.opentripplanner.org/"):
                    continue
                content = (await client.get(script)).text
                paths = re.findall(r'["`\\\'](/otp/(?:transmodel|gtfs)/[^"`\\\']+)["`\\\']', content)
                discovered.update(paths)
            report["ui_declared_api_paths"] = sorted(discovered)
            if len(discovered) == 1:
                path = next(iter(discovered))
                report["api_path"] = path
                response = await client.post(base_url + path, json={"query": SCHEMA_QUERY})
                response.raise_for_status()
                schema = response.json()
                if schema.get("data", {}).get("__schema"):
                    (target / "introspection.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
                    report["introspection_verified"] = True
                    report["reason"] = "API discovered from the installed UI; real route contract remains to be run."
                else:
                    report["reason"] = "UI-declared API did not return an introspection schema."
            else:
                report["reason"] = "No unique API endpoint established by installed UI evidence."
        except (httpx.HTTPError, ValueError) as exc:
            report["reason"] = f"Discovery failed: {type(exc).__name__}"
    (target / "connection-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return report


async def contract(input_path, output="data/otp"):
    from .routing import OTPAdapter, OTPSettings, evaluate_itineraries
    document = json.loads(Path(input_path).read_text(encoding="utf-8"))
    settings = OTPSettings.from_env()
    adapter = OTPAdapter(settings)
    try:
        result = await adapter.route(document["origin"], document["travel"])
        if result["status"] == "ok":
            result.update(evaluate_itineraries(result["itineraries"], document["travel"]))
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        (target / "contract-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": result["status"], "itineraries": len(result.get("itineraries", []))}, indent=2))
        return result
    finally:
        await adapter.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8821")
    parser.add_argument("--output", default="data/otp")
    parser.add_argument("--contract", help="Explicit JSON origin/travel input. No paid APIs are used.")
    args = parser.parse_args()
    asyncio.run(contract(args.contract, args.output) if args.contract else discover(args.base_url, args.output))


if __name__ == "__main__":
    main()
