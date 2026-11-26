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
from urllib.parse import urlencode

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


def read_ward_ids(data, source):
    features = data.get("features")
    if data.get("data_source") != source or not isinstance(features, list):
        return set()

    ward_ids = set()
    for feature in features:
        properties = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(properties, dict) or properties.get("data_source") != source:
            return set()
        ward_id = properties.get("ward_id")
        if not isinstance(ward_id, str) or not ward_id or ward_id in ward_ids:
            return set()
        ward_ids.add(ward_id)
    return ward_ids


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

    status, _, body = fetch(f"{api}/api/ready")
    readiness = safe_json(body)
    mode = readiness.get("mode")
    check(
        "API is ready with model data (/api/ready)",
        status == 200 and readiness.get("ready") is True and mode == "model",
        f"HTTP {status}, mode={mode}",
    )
    if status == 503 and isinstance(readiness.get("problems"), list):
        for problem in readiness["problems"]:
            print(f"INFO  {problem}")

    ward_ids = {}
    for source in ("model", "mock"):
        status, _, body = fetch(f"{api}/api/strategic/wards.geojson?source={source}")
        ids = read_ward_ids(safe_json(body), source) if status == 200 else set()
        ward_ids[source] = ids
        check(
            f"{source.capitalize()} ward GeoJSON has 23 correctly labelled wards",
            len(ids) == 23,
            f"HTTP {status}, {len(ids)} valid wards",
        )

    if len(ward_ids["model"]) == len(ward_ids["mock"]) == 23:
        check("Model and Mock cover the same Glasgow wards", ward_ids["model"] == ward_ids["mock"])

    if len(ward_ids["model"]) == 23:
        ward_id = min(ward_ids["model"])
        query = urlencode({"mode": "ward", "id": ward_id, "source": "model"})
        status, _, body = fetch(f"{api}/api/explain?{query}")
        explained = safe_json(body)
        text = explained.get("text")
        check(
            "Model ward explanation works (template fallback or provider)",
            status == 200
            and explained.get("id") == ward_id
            and explained.get("data_source") == "model"
            and explained.get("source") in ("fallback", "live")
            and isinstance(text, str)
            and bool(text.strip()),
            f"HTTP {status}, source={explained.get('source')}",
        )

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
        check(
            "API CORS allows the frontend origin",
            200 <= status < 300 and allowed in (frontend, "*"),
            f"HTTP {status}, allow-origin={allowed}",
        )

    print("OK" if not failures else f"{len(failures)} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
