#!/usr/bin/env python3
"""Read-only smoke check for a published Fire Sight frontend and API (GET/OPTIONS only).

    python scripts/smoke_check.py --api https://<api-host> [--frontend https://<frontend-host>]

Uses only the standard library. Exits non-zero if any check fails.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

TIMEOUT = 60  # free-tier hosts can take a while to wake


def fetch(url, headers=None, method="GET"):
    request = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()
    except (urllib.error.URLError, OSError) as err:
        return 0, {}, str(err).encode()


def safe_json(body):
    try:
        data = json.loads(body)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", required=True, help="API base URL, no trailing slash")
    parser.add_argument("--frontend", help="Frontend URL; also checks CORS for its origin")
    args = parser.parse_args(argv)
    api = args.api.rstrip("/")
    failures = []

    def check(name, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}  {name}{' - ' + detail if detail else ''}")
        if not ok:
            failures.append(name)

    status, _, body = fetch(f"{api}/api/health")
    check("API liveness (/api/health)", status == 200, f"HTTP {status}")

    status, _, body = fetch(f"{api}/api/status")
    info = safe_json(body) if status == 200 else {}
    check("API status reports model loaded", info.get("model_loaded") is True and info.get("forecast_available") is True, f"HTTP {status}")

    status, _, body = fetch(f"{api}/api/strategic/wards.geojson?source=model")
    features = safe_json(body).get("features", []) if status == 200 else []
    check("Model ward GeoJSON has 23 Glasgow wards", len(features) == 23, f"{len(features)} features")

    status, _, body = fetch(f"{api}/api/strategic/wards.geojson?source=mock")
    check("Mock ward GeoJSON has 23 wards", status == 200 and len(safe_json(body).get("features", [])) == 23, f"HTTP {status}")

    if features:
        ward_id = features[0]["properties"]["ward_id"]
        status, _, body = fetch(f"{api}/api/explain?mode=ward&id={ward_id}&source=model")
        explained = safe_json(body) if status == 200 else {}
        check("Explanation works (template fallback or provider)", explained.get("source") in {"fallback", "openai"} and bool(explained.get("text")), f"source={explained.get('source')}")

    status, _, _ = fetch(f"{api}/api/ready")
    print(f"INFO  /api/ready -> HTTP {status} (404 on older deployments; 503 means model data failed to load)")

    if args.frontend:
        frontend = args.frontend.rstrip("/")
        status, _, body = fetch(frontend + "/")
        check("Frontend serves the app shell", status == 200 and b'id="root"' in body, f"HTTP {status}")
        status, headers, _ = fetch(
            f"{api}/api/health",
            {"Origin": frontend, "Access-Control-Request-Method": "GET"},
            method="OPTIONS",
        )
        allowed = {k.lower(): v for k, v in headers.items()}.get("access-control-allow-origin")
        check("API CORS allows the frontend origin", allowed in (frontend, "*"), f"allow-origin={allowed}")

    print("OK" if not failures else f"{len(failures)} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
