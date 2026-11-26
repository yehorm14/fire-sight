import json
from urllib.parse import urlsplit

import pytest

import main
from scripts import smoke_check

API = "http://testserver"
FRONTEND = "http://127.0.0.1:5173"


@pytest.fixture
def smoke_fetch(client, monkeypatch):
    overrides = {}

    def fetch(url, headers=None, method="GET"):
        if (method, url) in overrides:
            return overrides[method, url]
        if url == f"{FRONTEND}/":
            return 200, {}, b'<div id="root"></div>'

        parsed = urlsplit(url)
        target = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        response = client.request(method, target, headers=headers)
        return response.status_code, dict(response.headers), response.content

    monkeypatch.setattr(smoke_check, "fetch", fetch)
    return overrides


@pytest.mark.parametrize("expected_source", ["fallback", "live"])
def test_release_smoke_uses_current_explanation_contract(smoke_fetch, monkeypatch, capsys, expected_source):
    provider_text = "Fixture explanation" if expected_source == "live" else None
    monkeypatch.setattr(main, "openai_explanation", lambda *args, **kwargs: provider_text)

    assert smoke_check.main(["--api", API, "--frontend", FRONTEND]) == 0
    assert f"HTTP 200, source={expected_source}" in capsys.readouterr().out


def test_release_smoke_fails_when_model_readiness_is_degraded(smoke_fetch, capsys):
    smoke_fetch["GET", f"{API}/api/ready"] = (
        503, {}, json.dumps({"ready": False, "mode": "degraded", "problems": ["Missing artifact"]}).encode()
    )

    assert smoke_check.main(["--api", API]) == 1
    output = capsys.readouterr().out
    assert "HTTP 503, mode=degraded" in output
    assert "INFO  Missing artifact" in output


def test_release_smoke_rejects_wrong_ward_source(smoke_fetch, client, capsys):
    mock_url = "/api/strategic/wards.geojson?source=mock"
    mock_response = client.get(mock_url)
    smoke_fetch["GET", f"{API}/api/strategic/wards.geojson?source=model"] = (
        mock_response.status_code, {}, mock_response.content
    )

    assert smoke_check.main(["--api", API]) == 1
    assert "Model ward GeoJSON has 23 correctly labelled wards - HTTP 200, 0 valid wards" in capsys.readouterr().out


def test_release_smoke_rejects_failed_cors_preflight(smoke_fetch, capsys):
    smoke_fetch["OPTIONS", f"{API}/api/health"] = (400, {"access-control-allow-origin": FRONTEND}, b"")

    assert smoke_check.main(["--api", API, "--frontend", FRONTEND]) == 1
    assert "FAIL  API CORS allows the frontend origin - HTTP 400" in capsys.readouterr().out
