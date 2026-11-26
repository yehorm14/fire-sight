"""Aggregate DataZone model output up to wards using an official DataZone-to-ward lookup.

The lookup is a CSV with columns ``datazone_id``, ``ward_id``, ``datazone_vintage``
and ``ward_vintage`` (for example the National Records of Scotland / Scottish
Government DataZone 2011 to electoral ward lookup, matching the ward vintage in
``glasgow_wards.geojson``). It is committed as
``data-pipeline/reference/datazone_ward_lookup.csv`` using the source and validation
procedure described in docs/PIPELINE.md.

Aggregation rule (``AGGREGATION_RULE``): a ward's score is the population-weighted
mean of the risk scores of the DataZones mapped to it. If no zone in a ward has a
positive population the plain mean is used.
"""
import csv
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

AGGREGATION_RULE = "population-weighted mean of DataZone risk scores"
LOOKUP_COLUMNS = {"datazone_id", "ward_id", "datazone_vintage", "ward_vintage"}


class LookupFormatError(ValueError):
    """Raised when the DataZone-to-ward lookup file is malformed."""


def load_lookup(path: Path) -> Optional[Dict[str, Any]]:
    """Read the ward mapping, boundary vintages and any official DataZone names."""
    if not path.exists():
        return None
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = LOOKUP_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise LookupFormatError(f"lookup is missing columns: {sorted(missing)}")
        rows = list(reader)
    mapping: Dict[str, str] = {}
    names: Dict[str, str] = {}
    for row in rows:
        zone = row["datazone_id"].strip()
        if zone in mapping:
            raise LookupFormatError(f"DataZone {zone} appears more than once in the lookup")
        mapping[zone] = row["ward_id"].strip()
        name = (row.get("datazone_name") or "").strip()
        if name:
            names[zone] = name
    dz_vintages = {r["datazone_vintage"].strip() for r in rows}
    ward_vintages = {r["ward_vintage"].strip() for r in rows}
    if len(dz_vintages) != 1 or len(ward_vintages) != 1 or "" in dz_vintages | ward_vintages:
        raise LookupFormatError("lookup must declare exactly one DataZone vintage and one ward vintage")
    return {
        "mapping": mapping,
        "names": names,
        "datazone_vintage": dz_vintages.pop(),
        "ward_vintage": ward_vintages.pop(),
    }


def aggregate_wards(
    zones: Iterable[Dict[str, Any]],
    mapping: Dict[str, str],
    ward_ids: Iterable[str],
    top_drivers: int = 3,
) -> Dict[str, Any]:
    """Aggregate zone records to wards.

    Returns {"wards": {ward_id: {...}}, "unmatched_zones": [...], "wards_without_zones": [...]}.
    """
    ward_ids = list(ward_ids)
    known = set(ward_ids)
    by_ward: Dict[str, List[Dict[str, Any]]] = {w: [] for w in ward_ids}
    unmatched: List[str] = []
    for zone in zones:
        ward = mapping.get(zone["zoneid"])
        if ward is None or ward not in known or zone.get("riskscore") is None:
            unmatched.append(zone["zoneid"])
        else:
            by_ward[ward].append(zone)

    wards: Dict[str, Dict[str, Any]] = {}
    for ward, members in by_ward.items():
        if not members:
            continue
        weights = [max(float(z.get("population") or 0), 0.0) for z in members]
        if sum(weights) <= 0:
            weights = [1.0] * len(members)
        total = sum(weights)
        score = sum(w * float(z["riskscore"]) for w, z in zip(weights, members)) / total
        driver_weight: Counter = Counter()
        for w, z in zip(weights, members):
            if not w:
                continue
            for driver in z.get("drivers") or []:
                driver_weight[driver] += w
        wards[ward] = {
            "risk_score": int(round(score)),
            "zone_count": len(members),
            "drivers": [d for d, _ in driver_weight.most_common(top_drivers)],
        }
    return {
        "wards": wards,
        "unmatched_zones": sorted(unmatched),
        "wards_without_zones": sorted(w for w in ward_ids if w not in wards),
    }
