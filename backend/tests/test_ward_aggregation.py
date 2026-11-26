import csv

import pytest

import main
import ward_aggregation as wa

ZONES = [
    {"zoneid": "Z1", "riskscore": 80, "population": 300, "drivers": ["A", "B"]},
    {"zoneid": "Z2", "riskscore": 20, "population": 100, "drivers": ["B", "C"]},
    {"zoneid": "Z3", "riskscore": 50, "population": 500, "drivers": ["C"]},
    {"zoneid": "Z4", "riskscore": 90, "population": 50, "drivers": []},
]


def test_population_weighted_ward_score_and_unmatched_reporting():
    result = wa.aggregate_wards(ZONES, {"Z1": "W1", "Z2": "W1", "Z3": "W2"}, ["W1", "W2", "W3"])
    assert result["wards"]["W1"]["risk_score"] == 65  # (80*300 + 20*100) / 400
    assert result["wards"]["W1"]["zone_count"] == 2
    assert result["wards"]["W2"]["risk_score"] == 50
    assert result["unmatched_zones"] == ["Z4"]
    assert result["wards_without_zones"] == ["W3"]


def test_drivers_come_from_the_wards_own_zones():
    result = wa.aggregate_wards(ZONES, {"Z1": "W1", "Z2": "W1", "Z3": "W2"}, ["W1", "W2"])
    assert result["wards"]["W1"]["drivers"] == ["B", "A", "C"]  # weights B=400, A=300, C=100
    assert result["wards"]["W2"]["drivers"] == ["C"]


def test_zero_weight_zones_do_not_supply_drivers():
    zones = [{**ZONES[0], "population": 0}, ZONES[2]]
    result = wa.aggregate_wards(zones, {"Z1": "W1", "Z3": "W1"}, ["W1"])
    assert result["wards"]["W1"]["drivers"] == ["C"]


def test_two_wards_in_same_decile_get_different_scores():
    # The old proxy gave every ward in a decile the same citywide mean.
    result = wa.aggregate_wards(ZONES, {"Z1": "W1", "Z2": "W2"}, ["W1", "W2"])
    assert result["wards"]["W1"]["risk_score"] != result["wards"]["W2"]["risk_score"]


def write_lookup(path, rows, header=("datazone_id", "ward_id", "datazone_vintage", "ward_vintage")):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_load_lookup_validates(tmp_path):
    assert wa.load_lookup(tmp_path / "missing.csv") is None
    good = tmp_path / "good.csv"
    write_lookup(good, [("Z1", "W1", "DZ2011", "WD24"), ("Z2", "W1", "DZ2011", "WD24")])
    assert wa.load_lookup(good)["mapping"] == {"Z1": "W1", "Z2": "W1"}

    dup = tmp_path / "dup.csv"
    write_lookup(dup, [("Z1", "W1", "DZ2011", "WD24"), ("Z1", "W2", "DZ2011", "WD24")])
    with pytest.raises(wa.LookupFormatError):
        wa.load_lookup(dup)

    mixed = tmp_path / "mixed.csv"
    write_lookup(mixed, [("Z1", "W1", "DZ2011", "WD24"), ("Z2", "W1", "DZ2011", "WD22")])
    with pytest.raises(wa.LookupFormatError):
        wa.load_lookup(mixed)

    bad = tmp_path / "bad.csv"
    write_lookup(bad, [("Z1", "W1")], header=("datazone_id", "ward_id"))
    with pytest.raises(wa.LookupFormatError):
        wa.load_lookup(bad)


def test_model_mode_without_lookup_is_labelled_proxy_and_drops_sample_fields(client, monkeypatch):
    monkeypatch.setitem(main.ward_aggregates, "wards", {})
    props = client.get("/api/strategic/wards/S13002967", params={"source": "model"}).json()["properties"]
    assert props["score_method"] == "simd_decile_proxy"
    assert "Proxy" in props["score_method_note"]
    for key in main.SAMPLE_WARD_PROPS:
        assert key not in props or key == "drivers"
    assert props["drivers"] == []


def test_model_mode_with_lookup_uses_ward_zones(client, monkeypatch):
    ward = "S13002967"
    zone_ids = [z["zoneid"] for z in main.zones[:3]]
    agg = wa.aggregate_wards(main.zones, {z: ward for z in zone_ids}, list(main.wards_by_id))
    monkeypatch.setitem(main.ward_aggregates, "wards", agg["wards"])
    props = client.get(f"/api/strategic/wards/{ward}", params={"source": "model"}).json()["properties"]
    assert props["score_method"] == "datazone_aggregate"
    assert props["zone_count"] == 3
    expected = agg["wards"][ward]["risk_score"]
    assert props["risk_score"] == expected
    assert props["drivers"] == agg["wards"][ward]["drivers"]
    assert "population-weighted" in props["score_method_note"]


def test_committed_lookup_covers_every_modeled_zone_and_ward(client):
    lookup = wa.load_lookup(main.DATAZONE_WARD_LOOKUP_CSV)
    assert lookup["datazone_vintage"] == "DZ2011"
    assert lookup["ward_vintage"] == "WD24"
    assert set(lookup["mapping"]) == set(main.zones_by_id)
    assert set(lookup["mapping"].values()) == set(main.wards_by_id)
    assert main.ward_aggregates["unmatched_zones"] == []
    assert main.ward_aggregates["wards_without_zones"] == []

    response = client.get("/api/strategic/wards.geojson", params={"source": "model"})
    assert response.status_code == 200
    properties = [feature["properties"] for feature in response.json()["features"]]
    assert len(properties) == len(main.wards_by_id)
    assert sum(ward["zone_count"] for ward in properties) == len(main.zones_by_id)
    for ward in properties:
        assert ward["score_method"] == "datazone_aggregate"
        assert ward["zone_count"] > 0
        assert set(main.SAMPLE_WARD_PROPS).isdisjoint(ward.keys() - {"drivers"})
