"""Verify that successive observations represent successive financial years."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-pipeline"))

from evaluate_ward_forecasts import rolling_predictions, summarize
from ward_forecasts import WARD_HISTORY_CSV, load_ward_projections, mapped_ward_codes, project_wards


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



def test_duplicate_ward_year_is_rejected(annual_history):
    duplicated = pd.concat([annual_history, annual_history.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate ward and financial-year"):
        project_wards(duplicated, {"WARD"})


def test_zero_is_observed_but_a_missing_count_is_rejected(annual_history):
    zero = annual_history.assign(Value=[0, 20, 30])
    assert project_wards(zero, {"WARD"}).iloc[0]["history_annual"] == [0, 20, 30]

    missing = annual_history.assign(Value=[None, 20, 30])
    with pytest.raises(ValueError, match="Missing dwelling-fire count"):
        project_wards(missing, {"WARD"})


def test_backtest_only_uses_years_up_to_the_forecast_origin(annual_history):
    years = [f"{year}/{year + 1}" for year in range(2009, 2017)]
    history = pd.DataFrame([annual_history.iloc[0].to_dict()] * len(years)).assign(
        DateCode=years, Value=[1, 2, 3, 4, 5, 6, 1000, 2000]
    )
    cases = rolling_predictions(history, {"WARD"})
    first = cases.loc[cases["origin"].eq("2014/2015")]
    assert first["target"].tolist() == ["2015/2016", "2016/2017"]
    assert first["weighted_trend"].tolist() == [7, 8]
    assert first["last_value"].tolist() == [6, 6]
    assert first["moving_average_3yr"].tolist() == [5, 5]
    assert first["observed"].tolist() == [1000, 2000]


def test_committed_ward_history_reproduces_forecast_and_backtest():
    forecasts = load_ward_projections().to_csv(index=False, lineterminator="\n")
    production = WARD_HISTORY_CSV.parent.parent / "output" / "glasgow_ward_forecasts.csv"
    assert forecasts == production.read_text()

    cases = rolling_predictions(pd.read_csv(WARD_HISTORY_CSV), mapped_ward_codes())
    summary = summarize(cases)
    trend = [row for row in summary if row["model"] == "weighted_trend"]
    assert [row["cases"] for row in trend] == [184, 161, 138]
    assert [row["covered_cases"] for row in trend] == [162, 126, 101]
