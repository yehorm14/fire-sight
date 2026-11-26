# Glasgow ward forecast evaluation

The three-year moving average had the lowest historical mean absolute error at all three leads. The weighted trend's residual range covered 88% of one-year observations and 73% of three-year observations. The dashboard still displays the weighted trend and its historical projections for FY2023/24–FY2025/26. These results do not establish operational accuracy.

## Reproduce the backtest

From the repository root, install `data-pipeline/requirements.txt` and run:

```bash
python data-pipeline/evaluate_ward_forecasts.py
```

The evaluator reads the checked-in [ward observation snapshot](../data-pipeline/reference/glasgow_ward_dwelling_fires.csv) and prints JSON with input hashes and metrics. Pass `--fire-csv PATH` to evaluate the same series directly from an official source CSV.

The first origin trains on six observed financial years through FY2014/15 for each ward. Each subsequent origin adds one year, fits the same model as production and predicts each of the next three individual financial years with an available observation. All three methods use identical ward/year targets at each lead. The last-value and three-year moving average baselines repeat the latest count or the mean of the last three observed counts respectively at every lead. The moving average is rounded to a whole count like the weighted trend. Error is forecast minus observed, so negative bias means underprediction.

| Lead | Method | Cases | MAE | RMSE | Bias | Range coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 year | Weighted trend | 184 | 7.55 | 10.13 | −1.42 | 162/184 (88.0%) |
| 1 year | Last value | 184 | 8.17 | 10.50 | +1.25 | — |
| 1 year | Three-year mean | 184 | **7.35** | 9.43 | +2.14 | — |
| 2 years | Weighted trend | 161 | 9.54 | 12.22 | −2.20 | 126/161 (78.3%) |
| 2 years | Last value | 161 | 8.68 | 11.34 | +2.46 | — |
| 2 years | Three-year mean | 161 | **8.15** | 10.45 | +3.24 | — |
| 3 years | Weighted trend | 138 | 11.31 | 14.66 | −3.22 | 101/138 (73.2%) |
| 3 years | Last value | 138 | 9.84 | 12.61 | +3.84 | — |
| 3 years | Three-year mean | 138 | **8.63** | 11.21 | +4.25 | — |

Errors are dwelling fires per ward per financial year. The two baselines make point predictions. Coverage measures how often the observed count fell within the production model's fitted residual range, including either endpoint. Observations overlap across forecast origins and share citywide conditions. The evaluation uses an updated snapshot of historical totals, without reproducing what was available at each release date.

## Source and coverage

The [Fire – Type of Incident release](https://data.gov.scot/dataset/fire___type_of_incident), listed on 13 August 2026 by the Scottish Government, supplies 322 direct observations for 23 wards from FY2009/10 through FY2022/23. The extraction retains official `Electoral Wards` rows with `Type Of Fire = Dwelling Fire`, `Accident Status = All`, `Measurement = Count` and `Units = Fires` for the 23 IDs in the [ONS May 2024 ward boundaries](https://www.data.gov.uk/dataset/faf874fd-aee8-4ca0-a4a9-4c8885ba3e82/wards-may-2024-boundaries-uk-bgc). Observations with missing values or duplicate keys fail validation. Recorded zero is a valid count.

| Input | SHA-256 |
| --- | --- |
| Original Fire – Type of Incident CSV, resource `f6b74111-b687-45dc-885d-66857bef37ba` | `ad3bb916071480bd913157a8bbdb28532cbff172162a6c0fc32333e0234f9f94` |
| Filtered ward observation snapshot | `7bf600b93ff765de52f141e376e65f95af7f830c2ba97b389847e55104eb211c` |
| Bundled WD24 map | `86fa0fc0112b1335cff186e06fc006249438ea37a31618894e9ac9f2b06c01cd` |
| Regenerated production forecast CSV | `615c49b4eb38b77a64e8d13857946a43a7856ae110706fa03b6d0ad809f84921` |

Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

The [SFRS incident workbook published 30 October 2026](https://www.firescotland.gov.uk/publications/document/?id=9990) provides incident records through FY2025/26 with dates, council codes and 2022 DataZone codes. It uses the dwelling-fire category, but supplies no direct ward codes or point locations. The workbook SHA-256 is `a9fa5a8e017ad4dce29dd57d2abbce520ca4af31aa415036487991bcfe88ba5d`. The [2022 Data Zone Lookup](https://data.gov.scot/dataset/2022_data_zone_lookup), published 19 August 2026, maps all Glasgow dwelling-fire records in that workbook to the same 23 ward codes (`DZ22_Code` to `MMWard_Code`). The lookup CSV SHA-256 is `41f51a4c0e6edbd30f81c3d8d79c37f3f557a3c1d887a10b75c07f0bc01e0891`.

Counting rows with `LACode = S12000049` and `IncidentType = Dwelling Fire` after that join yields a best-fit series for FY2009/10–FY2025/26. Only **99 of the 322** overlapping ward/year counts match the published direct observations. Differences run from −6 to +9 fires, despite almost identical citywide totals over the overlap (13,530 versus 13,525). Assigning whole DataZones to wards and revisions to the source can both contribute to those differences. The newer release can support a separately labelled best-fit series. Extending the direct observed series still requires a comparable ward release. The [Total Fires release](https://data.gov.scot/dataset/total_fires) covers all fire types and does not provide comparable ward dwelling-fire counts.

## Vulnerability score sensitivity

The DataZone vulnerability composite uses separate inputs and weights from the ward count forecast. The SIMD overall decile already includes housing, health and crime domains. Combining it with indicators from those domains gives overlapping signals and can make the ranking sensitive to the assigned weights. The forecast backtest cannot validate those weights or turn the composite into a fire probability. See the [SIMD technical notes](https://www.gov.scot/publications/simd-2020-technical-notes/) and the [CIF correction and ranking comparison](PIPELINE.md#datazone-score-version-2).

As a ranking sensitivity check on the corrected version 2 scores, shifting each of the five weights up and down by five percentage points while rescaling the other four proportionally retained between 67 and 73 of the original 75 highest-scoring DataZones. The largest individual score change across the ten scenarios was five points. This comparison uses the same clipped normalisation, missing-component handling and rounding as the production score, with equal scores ordered by DataZone code.
