"""Verify the matched, time-ordered candidate replay and direct city calibration."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-pipeline"))

from evaluate_candidate_forecasts import (
    CANDIDATE_CSV,
    HOLDOUT_ORIGIN,
    MODEL,
    add_intervals,
    city_cases,
    evaluate,
    point_cases,
    precision,
)
from pooled_ward_forecast import forecast_pooled_wards
from ward_forecasts import mapped_ward_codes


def financial_year(year):
    return f"{year}/{year + 1}"


def test_pooled_model_uses_ward_levels_and_a_shared_proportional_trend():
    counts = [[2, 4, 8, 16, 32], [6, 12, 24, 48, 96], [0, 0, 0, 0, 0]]
    assert np.allclose(forecast_pooled_wards(counts, (1, 2)), [[64, 128], [192, 384], [0, 0]])


def test_holdout_label_changes_cannot_affect_pre_holdout_forecasts():
    observations = pd.read_csv(CANDIDATE_CSV)
    wards = mapped_ward_codes()
    altered = observations.assign(Value=observations["Value"].where(
        observations["DateCode"].le(HOLDOUT_ORIGIN), observations["Value"] + 5000,
    ))
    original = point_cases(observations, wards)
    changed = point_cases(altered, wards)

    forecast_columns = ["ward_id", "target", "origin", "lead", MODEL, "weighted_trend",
                        "last_value", "moving_average_3yr"]
    pd.testing.assert_frame_equal(
        original.loc[original["origin"].le(HOLDOUT_ORIGIN), forecast_columns],
        changed.loc[changed["origin"].le(HOLDOUT_ORIGIN), forecast_columns],
    )


def test_calibration_requires_strictly_earlier_targets_at_the_same_lead():
    records = []
    for origin in range(2015, 2021):
        records.append({
            "model": MODEL, "origin": financial_year(origin), "target": financial_year(origin + 1),
            "lead": 1, "forecast": 10, "observed": 12 if origin < 2019 else 4000,
        })
    records.append({
        "model": MODEL, "origin": "2020/2021", "target": "2022/2023",
        "lead": 2, "forecast": 10, "observed": 0,
    })

    calibrated = add_intervals(pd.DataFrame(records), scale_by_forecast=False)
    early = calibrated.loc[calibrated["origin"].eq("2019/2020")].iloc[0]
    assert pd.isna(early["lower"])
    latest = calibrated.loc[calibrated["origin"].eq("2020/2021") & calibrated["lead"].eq(1)].iloc[0]
    assert latest["calibration_years"] == 4
    assert latest["calibration_cases"] == 4
    assert latest["last_calibration_target"] == "2019/2020"
    assert (latest["lower"], latest["upper"]) == (8, 12)
    other_lead = calibrated.loc[calibrated["lead"].eq(2)].iloc[0]
    assert pd.isna(other_lead["upper"])


def test_city_calibration_uses_city_residuals_instead_of_summing_ward_ranges():
    points = pd.DataFrame([
        {"ward_id": ward, "model": MODEL, "origin": financial_year(origin),
         "target": financial_year(origin + 1), "lead": 1, "forecast": 10, "observed": actual}
        for origin in range(2015, 2021)
        for ward, actual in (("first", 0), ("second", 20))
    ])
    origin = "2020/2021"
    wards = add_intervals(points, scale_by_forecast=True)
    wards = wards.loc[wards["origin"].eq(origin)]
    cities = add_intervals(city_cases(points), scale_by_forecast=False)
    city = cities.loc[cities["origin"].eq(origin)].iloc[0]
    assert city["last_calibration_target"] == "2019/2020"
    assert city["calibration_cases"] == 4
    assert city["lower"] == city["upper"] == 20
    assert wards["upper"].sum() > city["upper"]


def test_pinned_candidate_evaluation_matches_report():
    report_path = CANDIDATE_CSV.parent / "sfrs_candidate_forecast_evaluation_fy2025_26.json"
    expected = json.loads(report_path.read_text(encoding="utf-8"))
    actual = precision(evaluate())
    assert actual == expected
    assert [actual["full"][str(lead)]["models"][MODEL]["ward"]["cases"] for lead in (1, 2, 3)] == [
        161, 138, 115,
    ]
    decision = actual["promotion_decision"]
    assert decision["accuracy"]["fixed_holdout"]["passed"]
    assert not decision["city_bias_passed"]
    assert not decision["intervals_passed"]
    assert not decision["candidate_eligible_for_promotion"]
