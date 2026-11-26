"""A Poisson count model with one ward intercept and a shared proportional trend."""

import numpy as np


def forecast_pooled_wards(counts, horizons=(1, 2, 3)):
    """Forecast each row of a complete ward-by-year panel using only its columns."""
    counts = np.asarray(counts, dtype=float)
    if (counts.ndim != 2 or counts.shape[1] < 2 or not np.isfinite(counts).all()
            or (counts < 0).any() or (counts % 1 != 0).any()):
        raise ValueError("Expected at least two years of complete non-negative integer ward counts")

    ward_totals = counts.sum(axis=1)
    year_totals = counts.sum(axis=0)
    if not year_totals.any():
        return np.zeros((len(ward_totals), len(horizons)))

    years = np.arange(1 - counts.shape[1], 1, dtype=float)
    observed_time = float(year_totals @ years / year_totals.sum())
    if not years[0] < observed_time < years[-1]:
        raise ValueError("A shared Poisson slope requires counts beyond one endpoint year")

    # Complete panels have the same time weights for all wards. After maximizing
    # over the ward intercepts, the slope equates weighted and observed mean time.
    lower, upper = -100.0, 100.0
    for _ in range(80):
        slope = (lower + upper) / 2
        log_weights = slope * years
        log_weights -= log_weights.max()
        weights = np.exp(log_weights)
        fitted_time = float(weights @ years / weights.sum())
        if fitted_time < observed_time:
            lower = slope
        else:
            upper = slope

    slope = (lower + upper) / 2
    log_weights = slope * years
    max_log_weight = log_weights.max()
    normalizer = max_log_weight + np.log(np.exp(log_weights - max_log_weight).sum())
    future_weights = np.exp(slope * np.asarray(horizons) - normalizer)
    return ward_totals[:, None] * future_weights
