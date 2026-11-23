"""Smoke tests for the Fire Sight API, run against the committed data files."""

GOVAN = "S13002971"
NORTH_EAST = "S13003133"  # last ward in the model output; easy to miss in filters


def test_health_reports_loaded_datasets(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["wards_loaded"] == 23
    assert body["premises_loaded"] == 14
    assert body["zones_loaded"] == 746


def test_status_reports_model_and_forecasts(client):
    body = client.get("/api/status").json()
    assert body["model_loaded"] is True
    assert body["ward_forecasts_count"] == 23
    assert body["model_components_active"] == 5


def test_modes_lists_strategic_and_premises(client):
    modes = client.get("/api/modes").json()["modes"]
    assert [m["id"] for m in modes] == ["strategic", "premises"]


def test_wards_summary_list(client):
    wards = client.get("/api/strategic/wards").json()
    assert len(wards) == 23
    assert {"ward_id", "risk_score", "risk_band", "drivers", "prediction"} <= wards[0].keys()


def test_wards_geojson_mock_and_model_sources(client):
    for source in ("mock", "model"):
        data = client.get("/api/strategic/wards.geojson", params={"source": source}).json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 23
        props = data["features"][0]["properties"]
        assert props["data_source"] == source
        assert props["risk_band"] in {"low", "medium", "high"}
        assert data["features"][0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}


def test_model_source_has_forecast_for_every_ward(client):
    data = client.get("/api/strategic/wards.geojson", params={"source": "model"}).json()
    for feature in data["features"]:
        prediction = feature["properties"]["prediction"]
        assert prediction["period_unit"] == "financial_year"
        assert [step["lead"] for step in prediction["projections"]] == [1, 2, 3]
        for step in prediction["projections"]:
            assert step["lower"] <= step["forecast"] <= step["upper"]


def test_single_ward_and_404(client):
    ok = client.get(f"/api/strategic/wards/{NORTH_EAST}", params={"source": "model"})
    assert ok.status_code == 200
    assert ok.json()["properties"]["ward_name"] == "North East"
    assert client.get("/api/strategic/wards/NOPE").status_code == 404


def test_zones_top_is_sorted_by_rank(client):
    zones = client.get("/api/zones/top", params={"n": 5}).json()
    assert len(zones) == 5
    ranks = [z["riskrank"] for z in zones]
    assert ranks == sorted(ranks)
    assert ranks[0] == 1


def test_zones_list_and_single_zone(client):
    zones = client.get("/api/zones").json()
    assert len(zones) == 746
    zone_id = zones[0]["zoneid"]
    assert client.get(f"/api/zones/{zone_id}").json()["zoneid"] == zone_id
    assert client.get("/api/zones/NOPE").status_code == 404


def test_premises_list_filters_and_detail(client):
    all_items = client.get("/api/premises").json()
    assert len(all_items) == 14
    high = client.get("/api/premises", params={"risk_band": "high"}).json()
    assert high and all(item["risk_band"] == "high" for item in high)
    assert client.get("/api/premises/P001").json()["id"] == "P001"
    assert client.get("/api/premises/NOPE").status_code == 404


def test_explain_falls_back_without_openai_key(client):
    cases = [
        {"mode": "ward", "id": GOVAN, "source": "mock"},
        {"mode": "ward", "id": GOVAN, "source": "model"},
        {"mode": "premises", "id": "P001"},
        {"mode": "zone", "id": client.get("/api/zones/top", params={"n": 1}).json()[0]["zoneid"]},
    ]
    for params in cases:
        response = client.get("/api/explain", params=params)
        assert response.status_code == 200, params
        body = response.json()
        assert body["source"] == "fallback"
        assert body["text"].count("•") == 3


def test_explain_rejects_bad_input(client):
    assert client.get("/api/explain", params={"mode": "bogus", "id": "x"}).status_code == 400
    assert client.get("/api/explain", params={"mode": "ward", "id": "NOPE"}).status_code == 404


def test_cors_allows_local_frontend_only(client):
    headers = {"Access-Control-Request-Method": "GET"}
    allowed = client.options("/api/health", headers={**headers, "Origin": "http://localhost:5173"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"
    blocked = client.options("/api/health", headers={**headers, "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


def test_model_forecast_reports_years_from_data(client):
    props = client.get(f"/api/strategic/wards/{NORTH_EAST}", params={"source": "model"}).json()["properties"]
    prediction = props["prediction"]
    assert prediction["years_of_data"] == 14
    assert (prediction["first_year"], prediction["last_year"]) == (2009, 2023)
    assert "14 years" in prediction["note"] and "2009–2023" in prediction["note"]


def test_model_explain_text_uses_data_years(client):
    text = client.get("/api/explain", params={"mode": "ward", "id": GOVAN, "source": "model"}).json()["text"]
    assert "14 years of SFRS dwelling fire data (2009–2023)" in text


def test_cors_warning_when_unset_in_production(monkeypatch, caplog):
    import main

    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("RENDER", "true")
    with caplog.at_level("WARNING", logger="uvicorn.error"):
        origins = main.resolve_cors_origins()
    assert origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert "CORS_ORIGINS is not set" in caplog.text

    caplog.clear()
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example")
    assert main.resolve_cors_origins() == ["https://app.example"]
    assert "CORS_ORIGINS is not set" not in caplog.text


def test_model_projection_dates_and_legacy_client_aliases(client):
    status = client.get("/api/status").json()
    assert status["ward_projection_periods"] == [
        {"lead": 1, "financial_years": ["2023/2024"]},
        {"lead": 2, "financial_years": ["2024/2025"]},
        {"lead": 3, "financial_years": ["2025/2026"]},
    ]
    ward = client.get("/api/strategic/wards/S13002967", params={"source": "model"}).json()
    prediction = ward["properties"]["prediction"]
    assert prediction["source"] == "model"
    assert prediction["last_financial_year"] == "2022/2023"
    assert prediction["first_financial_year"] == "2009/2010"
    assert [(r["financial_year"], r["forecast"]) for r in prediction["projections"]] == [
        ("2023/2024", 30), ("2024/2025", 29), ("2025/2026", 28),
    ]
    assert [prediction[key] for key in ("forecast_6mo", "forecast_12mo", "forecast_18mo")] == [30, 29, 28]
    explain = client.get("/api/explain", params={
        "mode": "ward", "id": "S13002967", "source": "model", "lead": 3,
    }).json()["text"]
    assert "28 dwelling fires projected for FY 2025/2026" in explain


def test_legacy_ward_csv_has_only_the_saved_range(client, monkeypatch, tmp_path):
    import main

    old_csv = tmp_path / "legacy.csv"
    old_csv.write_text(
        "ward_id,first_year,last_year,years_of_data,forecast_6mo,forecast_12mo,forecast_18mo,"
        "forecast_lower,forecast_upper\n"
        "S13002967,2009,2023,14,30,29,28,11,49\n"
    )
    monkeypatch.setattr(main, "WARD_FORECASTS_CSV", old_csv)
    monkeypatch.setattr(main, "ward_forecasts", main.load_ward_forecasts())
    ward = client.get("/api/strategic/wards/S13002967", params={"source": "model"}).json()
    first, second, third = ward["properties"]["prediction"]["projections"]
    assert first == {"lead": 1, "financial_year": "2023/2024", "forecast": 30, "lower": 11, "upper": 49}
    assert second["financial_year"] == "2024/2025" and second["lower"] is None
    assert third["financial_year"] == "2025/2026" and third["upper"] is None


def test_mock_forecast_periods_are_sample_months(client):
    mock = client.get("/api/strategic/wards").json()[0]["prediction"]
    assert mock["source"] == "mock"
    assert mock["period_unit"] == "month"
    assert [step["lead"] for step in mock["projections"]] == [6, 12, 18]
    assert all("financial_year" not in step for step in mock["projections"])


class _FakeOpenAI:
    """Stand-in for openai.OpenAI that counts completion calls."""

    calls = 0

    def __init__(self, *args, **kwargs):
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        _FakeOpenAI.calls += 1
        content = f"• live explanation #{_FakeOpenAI.calls}"
        message = type("M", (), {"content": content})()
        return type("R", (), {"choices": [type("C", (), {"message": message})()]})()


def _use_fake_openai(monkeypatch):
    import sys
    import types

    import main

    _FakeOpenAI.calls = 0
    main._explanation_cache.clear()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_FakeOpenAI))


def test_explanation_is_cached_for_identical_requests(client, monkeypatch):
    _use_fake_openai(monkeypatch)
    url = f"/api/explain?mode=ward&id={GOVAN}&source=model&lead=1"
    first = client.get(url).json()
    second = client.get(url).json()
    assert first["source"] == "live"
    assert second["text"] == first["text"]
    assert _FakeOpenAI.calls == 1


def test_explanation_cache_separates_wards_and_leads(client, monkeypatch):
    _use_fake_openai(monkeypatch)
    base = "/api/explain?mode=ward"
    texts = {
        client.get(f"{base}&id={GOVAN}&source=model&lead=1").json()["text"],
        client.get(f"{base}&id={GOVAN}&source=model&lead=2").json()["text"],
        client.get(f"{base}&id={NORTH_EAST}&source=model&lead=1").json()["text"],
    }
    assert len(texts) == 3
    assert _FakeOpenAI.calls == 3


def test_explanation_cache_is_bounded(monkeypatch):
    import main

    main._explanation_cache.clear()
    monkeypatch.setattr(main, "EXPLANATION_CACHE_MAX", 3)
    for i in range(5):
        main._explanation_cache_put(("ward", str(i), "mock", None), "x")
    assert len(main._explanation_cache) == 3
    assert ("ward", "0", "mock", None) not in main._explanation_cache


# --- model-source contract -------------------------------------------------

def _all_source_urls():
    return [
        ("/api/strategic/wards", {}),
        ("/api/strategic/wards.geojson", {}),
        (f"/api/strategic/wards/{GOVAN}", {}),
        ("/api/explain", {"mode": "ward", "id": GOVAN}),
    ]


def test_every_endpoint_reports_resolved_source_and_version(client):
    for url, extra in _all_source_urls():
        model = client.get(url, params={**extra, "source": "model"})
        assert model.status_code == 200, url
        body = model.json()
        if isinstance(body, list):
            body = body[0]
        meta = body.get("properties", body)
        assert meta["data_source"] == "model", url
        assert len(meta["source_version"]) == 12, url
        mock = client.get(url, params={**extra, "source": "mock"})
        body = mock.json()
        if isinstance(body, list):
            body = body[0]
        meta = body.get("properties", body)
        assert (meta["data_source"], meta["source_version"]) == ("mock", "sample"), url


def test_unknown_source_is_rejected_everywhere(client):
    for url, extra in _all_source_urls():
        assert client.get(url, params={**extra, "source": "bogus"}).status_code == 400, url


def test_model_unavailable_is_503_never_sample_data(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "decile_to_model_score", {})
    for url, extra in _all_source_urls():
        res = client.get(url, params={**extra, "source": "model"})
        assert res.status_code == 503, url
        detail = res.json()["detail"]
        assert detail["error"] == "model_unavailable"
        assert "model score lookup is empty" in detail["reasons"]
        # demo mode is intentional and keeps working
        assert client.get(url, params={**extra, "source": "mock"}).status_code == 200, url


def test_missing_ward_forecasts_are_unavailable(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "ward_forecasts", {})
    for url, extra in _all_source_urls():
        assert client.get(url, params={**extra, "source": "model"}).status_code == 503, url


def test_partial_forecasts_fail_collection_but_serve_covered_ward(client, monkeypatch):
    import main

    only_govan = {GOVAN: main.ward_forecasts[GOVAN]}
    monkeypatch.setattr(main, "ward_forecasts", only_govan)
    res = client.get("/api/strategic/wards.geojson", params={"source": "model"})
    assert res.status_code == 503
    assert "no ward forecast for" in res.json()["detail"]["reasons"][0]
    assert client.get("/api/strategic/wards", params={"source": "model"}).status_code == 503
    assert client.get(f"/api/strategic/wards/{GOVAN}", params={"source": "model"}).status_code == 200
    assert client.get(f"/api/strategic/wards/{NORTH_EAST}", params={"source": "model"}).status_code == 503


def test_sources_agree_across_list_geojson_detail_and_explain(client):
    listed = {w["ward_id"]: w for w in client.get("/api/strategic/wards", params={"source": "model"}).json()}
    geo = client.get("/api/strategic/wards.geojson", params={"source": "model"}).json()
    detail = client.get(f"/api/strategic/wards/{GOVAN}", params={"source": "model"}).json()["properties"]
    explain = client.get("/api/explain", params={"mode": "ward", "id": GOVAN, "source": "model"}).json()
    by_id = {f["properties"]["id"]: f["properties"] for f in geo["features"]}
    assert listed[GOVAN]["risk_score"] == by_id[GOVAN]["risk_score"] == detail["risk_score"]
    assert listed[GOVAN]["data_source"] == explain["data_source"] == geo["data_source"] == "model"
    assert listed[GOVAN]["source_version"] == explain["source_version"] == geo["source_version"] == detail["source_version"]
