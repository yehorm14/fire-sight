"""Verify the versioned best-fit release without downloading the raw workbooks."""

import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-pipeline"))

from build_best_fit_ward_series import (
    BASENAME,
    GLASGOW,
    REFERENCE,
    YEARS,
    Ward,
    build,
    checked_incident_year,
    read_lookup,
    reconcile_councils,
    sha256,
    tally_incidents,
    tally_published,
)
from ward_forecasts import mapped_ward_codes, ward_observations


def test_incident_year_starts_in_april():
    assert checked_incident_year("2024-25", date(2025, 3, 31)) == 2024
    assert checked_incident_year("2025-26", date(2025, 4, 1)) == 2025
    with pytest.raises(ValueError, match="disagrees with fiscal year"):
        checked_incident_year("2024-25", date(2025, 4, 1))


@pytest.mark.parametrize(("council", "name", "zone", "reason"), [
    (None, "Glasgow City", "zone", "missing_council"),
    ("other", "Glasgow City", "zone", "unknown_council"),
    (GLASGOW, "Unknown", "zone", "council_name_disagreement"),
    (GLASGOW, "Glasgow City", None, "missing_datazone"),
    (GLASGOW, "Glasgow City", "unknown_zone", "unmatched_datazone"),
    (GLASGOW, "Glasgow City", "outside_glasgow", "council_code_disagreement"),
])
def test_unmappable_incident_blocks_release(council, name, zone, reason):
    zones = {"zone": Ward("ward", "Ward", GLASGOW),
             "outside_glasgow": Ward("other_ward", "Other ward", "other_council")}
    with pytest.raises(ValueError, match=reason):
        tally_incidents(
            [("Dwelling Fire", "2025-26", date(2025, 4, 1), council, name, zone)], zones,
            {GLASGOW: "Glasgow City"},
        )


def test_incident_rows_are_counted_even_when_visible_fields_repeat():
    incident = ("Dwelling Fire", "2025-26", date(2025, 4, 1), GLASGOW, "Glasgow City", "zone")
    wards, councils = tally_incidents(
        [incident, incident, ("Other Building Fire", *incident[1:])],
        {"zone": Ward("ward", "Ward", GLASGOW)}, {GLASGOW: "Glasgow City"},
    )
    assert wards == Counter({("ward", 2025): 2})
    assert councils == Counter({(GLASGOW, 2025): 2})


def test_reject_duplicate_datazone_rows(tmp_path):
    lookup = tmp_path / "lookup.csv"
    with lookup.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(("DZ22_Code", "MMWard_Code", "MMWard_Name", "LA_Code", "LA_Name"))
        writer.writerows([("zone", "ward", "Ward", GLASGOW, "Glasgow City")] * 2)
    with pytest.raises(ValueError, match="Duplicate DataZone"):
        read_lookup(lookup)


def test_published_council_years_must_be_unique():
    published_council_year = ("2024-25", "Glasgow City", (1, 0, 0, 0, 0, 0, 0, 0))
    with pytest.raises(ValueError, match="Duplicate published council/year"):
        tally_published([published_council_year] * 2, {"Glasgow City": GLASGOW})


def test_exclude_unnamed_rows_only_for_explicit_zero_counts():
    assert tally_published([("2024-25", None, (0,) * 8)], {}) == ({}, {2024: 0})
    with pytest.raises(ValueError, match="Unrecognised council"):
        tally_published([("2024-25", None, (1,) * 8)], {})
    with pytest.raises(ValueError, match="Invalid published dwelling counts"):
        tally_published([("2024-25", None, (None,) * 8)], {})


def test_missing_published_council_year_is_not_a_zero():
    with pytest.raises(ValueError, match="one row for every council and financial year"):
        reconcile_councils(Counter(), {}, {GLASGOW: "Glasgow City"})


def test_council_reconciliation_requires_matching_counts():
    published = {(GLASGOW, year): 0 for year in YEARS} | {(GLASGOW, 2025): 1}
    reconcile_councils(Counter({(GLASGOW, 2025): 1}), published, {GLASGOW: "Glasgow City"})
    with pytest.raises(ValueError, match="Incident and published council counts differ"):
        reconcile_councils(Counter(), published, {GLASGOW: "Glasgow City"})


def test_unpinned_input_cannot_write_candidate_release(tmp_path):
    source = tmp_path / "unexpected.xlsx"
    source.write_bytes(b"changed")
    output = tmp_path / "release"
    with pytest.raises(ValueError, match="pinned incidents SHA-256"):
        build(source, source, source, output)
    assert not output.exists()


def test_committed_panel_matches_manifest_and_existing_evaluator():
    path = REFERENCE / f"{BASENAME}.csv"
    panel = pd.read_csv(path)
    manifest = json.loads((REFERENCE / f"{BASENAME}.manifest.json").read_text())
    coverage = manifest["coverage"]
    assert manifest["artifact"] == {"name": path.name, "rows": len(panel), "sha256": sha256(path)}
    assert len(panel) == 6035
    assert panel["CouncilCode"].nunique() == 32
    assert panel["GeographyCode"].nunique() == 355
    assert not panel.duplicated(["GeographyCode", "DateCode"]).any()
    assert panel["Value"].notna().all()
    assert panel["Value"].ge(0).all()
    assert panel["Value"].eq(0).sum() == coverage["verified_zero_ward_years"] == 90
    assert panel["Value"].sum() == coverage["mapped_incidents"] == 88241
    assert coverage["published_council_years_reconciled"] == 544
    glasgow = ward_observations(panel, mapped_ward_codes())
    assert len(glasgow) == coverage["glasgow_ward_years"] == 391
    assert glasgow["CouncilCode"].eq(GLASGOW).all()
    assert glasgow.groupby("DateCode")["Value"].sum().to_dict() == manifest["glasgow_annual_totals"]
    assert manifest["glasgow_direct_overlap"]["exact_matches"] == 99
