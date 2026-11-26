"""Regression tests for production DataZone vulnerability generation."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-pipeline"))
from run_model import build_zones


def test_cif_keeps_the_published_ratio_across_populations():
    deciles = pd.DataFrame({
        "CA": ["S12000049"] * 4,
        "DataZone": ["small", "large", "missing", "high"],
        "IntZone": ["same-area"] * 4,
        "SIMD2020V2CountryDecile": [4] * 4,
    })
    indicators = pd.DataFrame({
        "Council_area": ["Glasgow City"] * 4,
        "Data_Zone": ["small", "large", "missing", "high"],
        "Total_population": [400, 1200, 800, 800],
        "overcrowded_rate": [0.2] * 4,
        "nocentralheat_rate": [0.1] * 4,
        "crime_rate": [80] * 4,
        "CIF": [125, 125, "*", 200],
    })

    scored = build_zones(deciles, indicators).set_index("zoneid")

    assert scored.loc["small", "cif_ratio"] == scored.loc["large", "cif_ratio"] == 125
    assert scored.loc["small", "riskscore"] == scored.loc["large", "riskscore"]
    assert scored.loc["high", "riskscore"] > scored.loc["large", "riskscore"]
    assert pd.isna(scored.loc["missing", "cif_ratio"])
    assert scored.loc["missing", "n_score_components"] == 4
    assert scored.loc["missing", "data_quality"] == "limited"
    assert "High comparative illness factor" not in scored.loc["missing", "drivers"]
