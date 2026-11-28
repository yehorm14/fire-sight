"""Contract checks for committed forecast artefacts and API readiness. No downloads."""
import csv
import shutil

import pytest
from fastapi.testclient import TestClient

import data_contract as dc
import main


def test_committed_artefacts_satisfy_contract():
    assert dc.check_all() == []


def test_manifest_matches_committed_files():
    manifest = dc.json.loads(dc.MANIFEST_JSON.read_text())
    assert manifest["history"]["last_financial_year"] == "2025/2026"
    assert manifest["projected_financial_years"] == ["2026/2027", "2027/2028", "2028/2029"]
    assert manifest["ward_forecast_release"] == dc.read_ward_release()
    assert manifest["files"]["glasgow_ward_forecasts.csv"]["rows"] == 23


@pytest.fixture
def data_copy(tmp_path):
    for src in (dc.WARD_FORECASTS_CSV, dc.ZONES_CSV, dc.MANIFEST_JSON):
        shutil.copy(src, tmp_path / src.name)
    return tmp_path


def test_load_ward_forecasts_validates_the_release_with_its_rows(data_copy):
    csv = data_copy / dc.WARD_FORECASTS_CSV.name
    manifest = data_copy / dc.MANIFEST_JSON.name
    result = main.load_ward_forecasts(csv, dc.WARDS_FILE, manifest)
    assert len(result.rows) == 23
    assert result.release == dc.json.loads(manifest.read_text())["ward_forecast_release"]
    assert all(dc.release_row_matches(row, result.release) for row in result.rows.values())
    assert result.release_problems == []

    csv.write_text(csv.read_text().replace(result.release["release_id"], "different_release", 1))
    mismatch = main.load_ward_forecasts(csv, dc.WARDS_FILE, manifest)
    assert any("interval metadata is invalid" in problem for problem in mismatch.release_problems)


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
    csv.write_text(csv.read_text().replace("2026/2027", "2026/27"))
    assert any("financial year" in p for p in dc.check_ward_forecasts(csv))


def test_missing_ward_is_reported(data_copy):
    csv = data_copy / "glasgow_ward_forecasts.csv"
    lines = csv.read_text().splitlines()
    csv.write_text("\n".join(lines[:-1]) + "\n")
    assert any("no forecast for wards" in p for p in dc.check_ward_forecasts(csv))


def test_blank_ward_id_is_reported(data_copy):
    csv = data_copy / dc.WARD_FORECASTS_CSV.name
    csv.write_text(csv.read_text().replace("S13002967,", ",", 1))
    assert any("unknown wards" in problem for problem in dc.check_ward_forecasts(csv))


def test_unreadable_forecast_header_is_reported(data_copy):
    csv = data_copy / dc.WARD_FORECASTS_CSV.name
    csv.write_bytes(b"\xff")
    problems = dc.check_manifest(data_copy / dc.MANIFEST_JSON.name, [csv])
    assert f"cannot read committed artifact: {csv.name}" in problems


def test_legacy_annual_csv_requires_ordered_numeric_bounds(data_copy):
    import pandas as pd

    csv = data_copy / "glasgow_ward_forecasts.csv"
    df = pd.read_csv(csv).drop(columns=list(dc.WARD_RELEASE_COLUMNS))
    for lead in dc.HORIZON_LEADS:
        df[f"forecast_lower_{lead}yr"] = df[f"forecast_{lead}yr"]
        df[f"forecast_upper_{lead}yr"] = df[f"forecast_{lead}yr"]
    df.to_csv(csv, index=False)
    assert dc.check_ward_forecasts(csv) == []

    df.loc[0, "forecast_lower_1yr"] += 5
    df.to_csv(csv, index=False)
    assert any("lower <= forecast <= upper" in p for p in dc.check_ward_forecasts(csv))


@pytest.mark.parametrize("column,value,reason", [
    ("forecast_lower_1yr", 9, "both bounds blank"),
    ("forecast_upper_2yr", 42, "both bounds blank"),
    ("forecast_3yr", 1.5, "non-negative whole forecast"),
    ("interval_status", "", "interval metadata is invalid"),
    ("interval_method", "residual_spread", "interval metadata is invalid"),
    ("interval_nominal_level", 0.8, "interval metadata is invalid"),
    ("forecast_release_id", "other_release", "interval metadata is invalid"),
])
def test_point_release_rejects_incompatible_bounds_and_metadata(data_copy, column, value, reason):
    import pandas as pd

    csv = data_copy / "glasgow_ward_forecasts.csv"
    df = pd.read_csv(csv).astype(object)
    df.loc[0, column] = value
    df.to_csv(csv, index=False)
    assert any(reason in problem for problem in dc.check_ward_forecasts(csv))


def test_undeclared_blank_bounds_are_invalid(data_copy):
    import pandas as pd

    csv = data_copy / "glasgow_ward_forecasts.csv"
    df = pd.read_csv(csv).drop(columns=list(dc.WARD_RELEASE_COLUMNS))
    df.to_csv(csv, index=False)
    assert any("lower <= forecast <= upper" in p for p in dc.check_ward_forecasts(csv))


def test_release_degrades_when_pinned_source_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(dc, "REFERENCE_DIR", tmp_path)
    with TestClient(main.create_app()) as client:
        response = client.get("/api/ready")
    assert response.status_code == 503
    assert any("ward observation input: cannot read" in problem for problem in response.json()["problems"])


def test_malformed_observation_source_reports_degraded_readiness(monkeypatch, tmp_path):
    release = dc.read_ward_release()
    release["observation_source"] = None
    release_path = tmp_path / dc.WARD_RELEASE_JSON.name
    release_path.write_text(dc.json.dumps(release))
    monkeypatch.setattr(dc, "WARD_RELEASE_JSON", release_path)

    assert dc.check_ward_forecasts() == [
        f"{dc.WARD_FORECASTS_CSV.name} references an invalid ward forecast observation source",
    ]
    with TestClient(main.create_app(ward_release_path=release_path)) as client:
        response = client.get("/api/ready")
    assert response.status_code == 503
    assert any("invalid ward forecast observation source" in problem for problem in response.json()["problems"])


def test_manifest_detects_changed_release_metadata(data_copy):
    path = data_copy / "manifest.json"
    manifest = dc.json.loads(path.read_text())
    manifest["ward_forecast_release"]["issue_date"] = "2026-11-27"
    path.write_text(dc.json.dumps(manifest))
    assert any("differs from the versioned release" in problem for problem in dc.check_manifest(path))


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


def test_liveness_is_independent_of_model_data(tmp_path):
    with TestClient(main.create_app(ward_forecasts_csv=tmp_path / "gone.csv")) as client:
        assert client.get("/api/health").json()["status"] == "ok"


def test_healthy_bundled_data_is_ready(client, monkeypatch):
    monkeypatch.delenv(main.MOCK_MODE_ENV, raising=False)
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "mode": "model", "mock_mode_enabled": False, "problems": []}
    assert client.get("/api/status").json()["data_mode"] == "model"


def test_missing_model_data_is_degraded_not_mock(monkeypatch, tmp_path):
    monkeypatch.delenv(main.MOCK_MODE_ENV, raising=False)
    with TestClient(main.create_app(ward_forecasts_csv=tmp_path / "gone.csv")) as client:
        response = client.get("/api/ready")
        assert client.get("/api/status").json()["data_mode"] == "degraded"
    assert response.status_code == 503
    body = response.json()
    assert body["mode"] == "degraded" and body["mock_mode_enabled"] is False
    assert "missing required file: gone.csv" in body["problems"]


def test_deliberate_mock_mode_is_distinguishable(monkeypatch, tmp_path):
    monkeypatch.setenv(main.MOCK_MODE_ENV, "1")
    with TestClient(main.create_app(ward_forecasts_csv=tmp_path / "gone.csv")) as client:
        response = client.get("/api/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "mock" and body["mock_mode_enabled"] is True
    assert body["problems"]  # failure details stay visible even in mock mode



def test_mismatched_release_is_unavailable_in_its_lifespan(data_copy):
    csv_path = data_copy / dc.WARD_FORECASTS_CSV.name
    release = dc.read_ward_release()
    csv_path.write_text(csv_path.read_text().replace(release["release_id"], "wrong_release", 1))
    app = main.create_app(ward_forecasts_csv=csv_path, manifest_path=data_copy / dc.MANIFEST_JSON.name)
    with TestClient(app) as client:
        ready = client.get("/api/ready")
        assert ready.status_code == 503
        status = client.get("/api/status").json()
        assert status["forecast_available"] is False
        assert status["ward_forecast_release"] is None

        ward = "/api/strategic/wards/S13002967"
        model = client.get(ward, params={"source": "model"})
        assert model.status_code == 503
        assert any("interval metadata is invalid" in reason for reason in model.json()["detail"]["reasons"])
        assert client.get(ward, params={"source": "mock"}).json()["properties"]["data_source"] == "mock"


def test_app_lifespans_have_independent_rows_and_metadata(data_copy):
    ward_id = "S13002967"
    ward = f"/api/strategic/wards/{ward_id}"
    csv_path = data_copy / dc.WARD_FORECASTS_CSV.name
    manifest_path = data_copy / dc.MANIFEST_JSON.name
    release_path = data_copy / dc.WARD_RELEASE_JSON.name
    release = dc.read_ward_release()
    release["release_id"] = "fixture_release"
    release_path.write_text(dc.json.dumps(release))
    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        columns = reader.fieldnames
    for row in rows:
        row["forecast_release_id"] = release["release_id"]
        if row["ward_id"] == ward_id:
            row["forecast_1yr"] = "42"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    manifest = dc.json.loads(manifest_path.read_text())
    manifest["ward_forecast_release"] = release
    manifest["files"][csv_path.name]["sha256"] = dc.sha256_of(csv_path)
    manifest_path.write_text(dc.json.dumps(manifest))

    default_app = main.create_app()
    fixture_app = main.create_app(
        ward_forecasts_csv=csv_path, ward_release_path=release_path, manifest_path=manifest_path,
    )
    with TestClient(default_app) as default, TestClient(fixture_app) as fixture:
        params = {"source": "model"}
        original = default.get(ward, params=params).json()["properties"]
        updated = fixture.get(ward, params=params).json()["properties"]
        assert original["prediction"]["forecast_release"] == dc.read_ward_release()
        assert updated["prediction"]["forecast_release"] == release
        assert original["prediction"]["projections"][0]["forecast"] != 42
        assert updated["prediction"]["projections"][0]["forecast"] == 42
        assert original["source_version"] != updated["source_version"]
        assert fixture.get("/api/ready").json()["problems"] == []
        assert fixture.get("/api/status").json()["ward_forecast_release"] == release
        explain = fixture.get("/api/explain", params={**params, "mode": "ward", "id": ward_id}).json()
        assert explain["forecast_release"] == release
        assert explain["projection"]["forecast"] == 42

        csv_path.unlink()
        release_path.unlink()
        assert fixture.get(ward, params=params).json()["properties"] == updated
        assert fixture.get("/api/ready").json()["problems"] == []
        assert default.get(ward, params=params).json()["properties"] == original
