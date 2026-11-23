"""Contract checks for committed forecast artefacts and API readiness. No downloads."""
import shutil

import pytest

import data_contract as dc
import main


def test_committed_artefacts_satisfy_contract():
    assert dc.check_all() == []


def test_manifest_matches_committed_files():
    manifest = dc.json.loads(dc.MANIFEST_JSON.read_text())
    assert manifest["history"]["last_financial_year"] == "2022/2023"
    assert manifest["projected_financial_years"] == ["2023/2024", "2024/2025", "2025/2026"]
    assert manifest["files"]["glasgow_ward_forecasts.csv"]["rows"] == 23


@pytest.fixture
def data_copy(tmp_path):
    for src in (dc.WARD_FORECASTS_CSV, dc.ZONES_CSV, dc.MANIFEST_JSON):
        shutil.copy(src, tmp_path / src.name)
    return tmp_path


def test_missing_forecast_file_is_reported(tmp_path):
    problems = dc.check_ward_forecasts(tmp_path / "glasgow_ward_forecasts.csv")
    assert problems == ["missing required file: glasgow_ward_forecasts.csv"]


def test_legacy_schema_is_rejected(data_copy):
    csv = data_copy / "glasgow_ward_forecasts.csv"
    csv.write_text("ward_id,forecast_6mo\nS13002967,30\n")
    problems = dc.check_ward_forecasts(csv)
    assert problems and "missing columns" in problems[0]


def test_month_based_periods_are_rejected(data_copy):
    csv = data_copy / "glasgow_ward_forecasts.csv"
    csv.write_text(csv.read_text().replace("2023/2024", "2023/24"))
    assert any("financial year" in p for p in dc.check_ward_forecasts(csv))


def test_missing_ward_is_reported(data_copy):
    csv = data_copy / "glasgow_ward_forecasts.csv"
    lines = csv.read_text().splitlines()
    csv.write_text("\n".join(lines[:-1]) + "\n")
    assert any("no forecast for wards" in p for p in dc.check_ward_forecasts(csv))


def test_inverted_bounds_are_reported(data_copy):
    import pandas as pd

    csv = data_copy / "glasgow_ward_forecasts.csv"
    df = pd.read_csv(csv)
    df.loc[0, "forecast_lower_1yr"] = df.loc[0, "forecast_upper_1yr"] + 5
    df.to_csv(csv, index=False)
    assert any("lower <= forecast <= upper" in p for p in dc.check_ward_forecasts(csv))


def test_edited_data_without_manifest_refresh_is_reported(data_copy):
    csv = data_copy / "glasgow_ward_forecasts.csv"
    csv.write_text(csv.read_text() + "\n")
    problems = dc.check_manifest(data_copy / "manifest.json", [csv])
    assert any("changed since the manifest" in p for p in problems)
    assert dc.check_manifest(data_copy / "nope.json") == ["missing provenance manifest: nope.json"]


def test_malformed_zone_csv_is_reported(tmp_path):
    csv = tmp_path / "glasgowzones.csv"
    csv.write_text("zoneid,riskscore\nA,1\n")
    assert "missing columns" in dc.check_zones(csv)[0]


def test_liveness_is_independent_of_model_data(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "WARD_FORECASTS_CSV", tmp_path / "gone.csv")
    assert client.get("/api/health").json()["status"] == "ok"


def test_healthy_bundled_data_is_ready(client, monkeypatch):
    monkeypatch.delenv(main.MOCK_MODE_ENV, raising=False)
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "mode": "model", "mock_mode_enabled": False, "problems": []}
    assert client.get("/api/status").json()["data_mode"] == "model"


def test_missing_model_data_is_degraded_not_mock(client, monkeypatch, tmp_path):
    monkeypatch.delenv(main.MOCK_MODE_ENV, raising=False)
    monkeypatch.setattr(main, "WARD_FORECASTS_CSV", tmp_path / "gone.csv")
    response = client.get("/api/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["mode"] == "degraded" and body["mock_mode_enabled"] is False
    assert "missing required file: gone.csv" in body["problems"]
    assert client.get("/api/status").json()["data_mode"] == "degraded"


def test_deliberate_mock_mode_is_distinguishable(client, monkeypatch, tmp_path):
    monkeypatch.setenv(main.MOCK_MODE_ENV, "1")
    monkeypatch.setattr(main, "WARD_FORECASTS_CSV", tmp_path / "gone.csv")
    response = client.get("/api/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "mock" and body["mock_mode_enabled"] is True
    assert body["problems"]  # failure details stay visible even in mock mode
