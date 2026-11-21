"""Verify that successive observations represent successive financial years."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-pipeline"))

from ward_forecasts import project_wards


@pytest.fixture
def annual_history():
    return pd.DataFrame({
        "GeographyCode": ["WARD"] * 3,
        "GeographyName": ["Fixture"] * 3,
        "DateCode": ["2019/2020", "2020/2021", "2021/2022"],
        "Type Of Fire": ["Dwelling Fire"] * 3,
        "Accident Status": ["All"] * 3,
        "Measurement": ["Count"] * 3,
        "Value": [10, 20, 30],
    })


def test_linear_trend_extrapolates_one_distinct_financial_year_per_step(annual_history):
    ward = project_wards(annual_history.iloc[::-1], {"WARD"}).iloc[0]
    assert ward["first_financial_year"] == "2019/2020"
    assert ward["last_financial_year"] == "2021/2022"
    assert ward["years_of_data"] == 3
    assert ward["history_annual"] == [10, 20, 30]
    for lead, date, expected in [(1, "2022/2023", 40), (2, "2023/2024", 50), (3, "2024/2025", 60)]:
        assert ward[f"financial_year_{lead}yr"] == date
        assert ward[f"forecast_{lead}yr"] == expected
        assert ward[f"forecast_lower_{lead}yr"] == ward[f"forecast_upper_{lead}yr"] == expected


def test_gapped_annual_observations_are_rejected(annual_history):
    with pytest.raises(ValueError, match="consecutive and unique"):
        project_wards(annual_history.drop(index=1), {"WARD"})
