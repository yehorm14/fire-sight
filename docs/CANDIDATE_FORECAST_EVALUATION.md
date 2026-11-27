# Best-fit ward forecast evaluation

**Advance the pooled Poisson model for further research. Retain the existing weighted trend as the point-forecast fallback.** The pooled model reduced ward error on matched targets and passed the accuracy gate. It missed the fixed-holdout city bias limit at two years, and its empirical prediction ranges did not pass the coverage gate. The [forecast release](PIPELINE.md#glasgow-ward-forecast-release) refits the fallback point model on the best-fit observations and records that prediction intervals were withheld.

## Data and replay

The [versioned FY2025/26 best-fit series](BEST_FIT_WARD_SERIES.md) gives 391 counts for Glasgow's 23 wards. The point comparison uses six years of training for the earliest calibration forecasts and ten for the first scored origin in FY2018/19. Each subsequent origin adds one observed financial year. For every lead, all four models predict the same ward, origin and target combinations. The origin is the last training financial year.

| Lead | First to last target | Distinct target years | Ward forecasts |
| --- | --- | ---: | ---: |
| 1 year | FY2019/20–FY2025/26 | 7 | 161 |
| 2 years | FY2020/21–FY2025/26 | 6 | 138 |
| 3 years | FY2021/22–FY2025/26 | 5 | 115 |

Use targets through FY2022/23 to assess development accuracy. The fixed comparison fits each model through FY2022/23 and predicts FY2023/24, FY2024/25 and FY2025/26, with one city observation and 23 wards per lead. The replay uses a single revised release and the same best-fit boundary assignment throughout history. It does not reconstruct archived release dates, revisions or an actual publication-time forecast. All features come from the training counts. The other 31 Scottish councils are reserved for external validation and did not contribute to the fitted models or intervals.

The pooled model fits one intercept per ward and one shared proportional change per year. The comparison includes the current recency-weighted ward trend, each ward's last observed count and its three-year mean. Point forecasts are rounded to whole counts before forming the city total.

## Prespecified promotion gates

1. Require at least a 5% improvement in ward MAE against the current trend when each lead is weighted equally, in both the development and fixed comparisons. Allow at most 5% MAE regression at any individual lead in either comparison.
2. Require the candidate's fixed-origin absolute city-total error to be at most 10% of the observed total at every lead.
3. Assess empirical intervals against nominal 80% coverage. Require five distinct evaluated target years per lead and coverage within 10 percentage points of nominal for both wards and city totals. Fewer years give an insufficient result.
4. Keep the current trend specification if any gate fails.

These screening thresholds were fixed before running this evaluation. They define when this candidate could advance to a release. They do not establish statistical significance or operational accuracy.

## Point forecasts

Each cell reports **MAE / signed bias** in fires. Positive bias means overprediction.

| Model | Ward 1 year | Ward 2 years | Ward 3 years | City 1 year | City 2 years | City 3 years |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Weighted trend | 6.54 / +0.59 | 7.41 / +1.45 | 8.73 / +1.83 | **30.43** / +13.57 | **33.33** / +33.33 | **43.20** / +42.00 |
| Last value | 7.06 / +1.73 | 7.79 / +4.05 | 9.07 / +5.78 | 42.14 / +39.86 | 93.17 / +93.17 | 133.00 / +133.00 |
| Three-year mean | 6.73 / +3.63 | 7.65 / +5.90 | 9.10 / +7.62 | 83.57 / +83.57 | 135.67 / +135.67 | 175.20 / +175.20 |
| Pooled Poisson | **5.73** / +0.66 | **5.61** / +1.43 | **5.70** / +1.70 | 39.86 / +15.29 | 34.33 / +33.00 | 51.60 / +39.20 |

The pooled model improved equally weighted ward MAE by **25.55%** in development and **26.62%** in the fixed holdout. The weighted trend has lower city MAE at all leads in the full replay. In the fixed comparison, the pooled model's two-year city error was **70 fires**, or **11.24%**, exceeding the 10% limit. The weighted trend's fixed city errors stayed within 10% at all leads.

| Fixed target | Actual city total | Pooled ward MAE / bias | Weighted ward MAE / bias | Pooled city forecast / error | Weighted city forecast / error |
| --- | ---: | ---: | ---: | ---: | ---: |
| FY2023/24 | 689 | 6.09 / +1.30 | 6.17 / +0.70 | 719 / +30 | 705 / +16 |
| FY2024/25 | 623 | 4.78 / +3.04 | 6.78 / +2.17 | 693 / +70 | 673 / +50 |
| FY2025/26 | 616 | 4.35 / +2.35 | 7.78 / +1.00 | 670 / +54 | 639 / +23 |

## Empirical prediction ranges

For each model and lead, calibrate only on forecasts whose completed targets **strictly precede** the current origin. Require four distinct completed target years to calculate a range. Ward calibration pools absolute errors scaled by the square root of the forecast, with the scale floored at one. City calibration uses absolute errors of the directly summed city point forecasts. The aggregate range is computed from these city errors. Take the finite-sample 80% order statistic, multiply by the forecast's scale, and round outwards with the lower bound clipped to zero.

Coverage is measured only on cases with a range. Forecasts reuse training years, wards share citywide shocks, and each city lead has few distinct observations. These empirical ranges carry no exchangeability guarantee.

| Lead | Evaluated target years | Pooled ward coverage / width | Pooled city coverage / width | Weighted ward coverage / width | Weighted city coverage / width |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 year | 6 | 134/138 (97.1%) / 25.1 | 6/6 (100%) / 248 | 125/138 (90.6%) / 24.9 | 6/6 (100%) / 239.3 |
| 2 years | 4 | 90/92 (97.8%) / 28.1 | 4/4 (100%) / 324 | 86/92 (93.5%) / 32.8 | 4/4 (100%) / 330 |
| 3 years | 2 | 46/46 (100%) / 29.1 | 2/2 (100%) / 442 | 46/46 (100%) / 41.1 | 2/2 (100%) / 540 |

The pooled and weighted ranges cover more than allowed at one year and have insufficient distinct target years at the longer leads. The existing weighted trend's fitted residual range on these same ward targets covers 152/161, 121/138 and 90/115, with widths 31.94, 32.05 and 32.17 fires. Those describe fitted residual variation and have no nominal calibration.

## Reproduce

Install `data-pipeline/requirements.txt` and run from the repository root:

```bash
python data-pipeline/evaluate_candidate_forecasts.py
```

The CLI verifies the candidate's hash and prints the [checked-in JSON report](../data-pipeline/reference/sfrs_candidate_forecast_evaluation_fy2025_26.json) including all models, split-specific errors and prediction ranges, and the gate results. The [direct-ward evaluation](FORECAST_EVALUATION.md) is a separate benchmark.
