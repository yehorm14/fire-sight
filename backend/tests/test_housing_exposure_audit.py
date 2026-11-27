"""Check housing release eligibility and the matched Poisson exposure calculation."""

from datetime import date
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data-pipeline"))
from audit_housing_exposure import DZ2022_RELEASE, LEGACY_RELEASE, eligible_origins, profiled_poisson


def test_no_modern_stock_release_was_available_at_any_matched_origin():
    assert eligible_origins(LEGACY_RELEASE) == {2024: [1]}
    assert eligible_origins(DZ2022_RELEASE) == {}
    assert eligible_origins(date(2025, 3, 31)) == {2024: [1]}
    assert eligible_origins(date(2025, 4, 1)) == {}


def test_exposure_scales_per_ward_expected_counts_after_an_omitted_training_year():
    years = [2019, 2021, 2022]
    stocks = np.array([[100, 200, 300], [400, 400, 500]])
    counts = stocks * np.array([[0.1], [0.2]])
    predicts = profiled_poisson(counts, years, 2023, stocks, [400, 600])
    np.testing.assert_allclose(predicts, [40, 120])


def test_exposure_must_be_complete_and_positive():
    with pytest.raises(ValueError, match="complete positive stock"):
        profiled_poisson([[1, 2]], [2019, 2020], 2021, [[20, 30]], [0])


def test_time_invariant_housing_feature_is_aliased_with_ward_intercepts():
    with pytest.raises(ValueError, match="within-ward"):
        profiled_poisson([[1, 2], [3, 4]], [2019, 2020], 2021,
                         feature=[[0.1, 0.1], [0.4, 0.4]], target_feature=[0.1, 0.4])
