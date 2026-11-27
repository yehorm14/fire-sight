# Data pipeline

`data-pipeline/run_model.py` scores each Glasgow DataZone from five SIMD 2020 indicators (area deprivation decile, overcrowding, comparative illness factor, no central heating, crime rate) with fixed weights. It also fits a recency-weighted linear trend to yearly SFRS dwelling-fire counts for the 23 wards in `backend/data/glasgow_wards.geojson` and projects each of the first three financial years after the last observation. The committed data use 2009/2010 through 2022/2023, so the projected years are 2023/2024, 2024/2025 and 2025/2026. Each value is one financial year's dwelling-fire count. `notebook.ipynb` contains exploratory sample half-year logic and writes only to `build/exploratory/`.

The processed output is committed in `data-pipeline/output/`, so the API runs without the raw data. The full raw downloads stay outside git. A compact official ward observation snapshot supports offline regeneration and evaluation.

## Regenerate the output

Install the pinned pipeline dependencies, then fetch the raw inputs and run the pipeline. The downloader skips files already in `data-pipeline/raw/` and exits non-zero if a required download fails.

```bash
python -m pip install -r data-pipeline/requirements.txt
python data-pipeline/download_datasets.py
python data-pipeline/run_model.py
```

The downloader fetches the [SIMD 2020v2 population-weighted deciles](https://www.opendata.nhs.scot/dataset/scottish-index-of-multiple-deprivation/resource/acade396-8430-4b34-895a-b3e757fa346e) as `raw/simd2020.csv`, the [SIMD 2020v2 indicators](https://www.gov.scot/publications/scottish-index-of-multiple-deprivation-2020v2-indicator-data/) as `raw/simd2020_indicators.xlsx` and the [SFRS fire statistics](https://data.gov.scot/dataset/fire___type_of_incident) as `raw/fire_statistics_scotland.csv`. The population-weighted deciles are the ones used for the original score. `--boundaries` also downloads DataZone boundaries and needs GeoPandas.

To rebuild just the DataZone scores and refresh the manifest:

```bash
python data-pipeline/download_datasets.py --zones-only
python data-pipeline/run_model.py --zones-only
python backend/data_contract.py --write-manifest
```

To regenerate only the ward projection CSV, run `python data-pipeline/ward_forecasts.py`. This reads the checked-in annual observations and uses the same forecast function as `run_model.py`. Use `--fire-csv PATH` to supply an official source CSV. Each ward must have consecutive, unique financial-year observations.

Run `python data-pipeline/evaluate_ward_forecasts.py` for the rolling-origin comparison against last-value and three-year mean baselines. See the [forecast evaluation](FORECAST_EVALUATION.md) for the source audit, out-of-sample errors and residual range coverage.

## Review regenerated data

`data-pipeline/output/manifest.json` records the sources, financial-year range and a SHA-256 for each committed CSV. CI runs `python backend/data_contract.py` (and the same checks inside pytest), so no download is needed. It checks required columns, one forecast per ward in `glasgow_wards.geojson`, annual financial-year labels for each lead (`2023/2024`, not month bins), ordered bounds, and that the CSVs still match the manifest.

When upstream inputs change:

1. Run the regeneration steps above.
2. `python backend/data_contract.py --write-manifest` (refuses to write if the contract fails).
3. Review the `git diff` of both CSVs and the manifest (ward counts, projected years, large forecast moves) and update test expectations that name specific years or counts.

## DataZone score version 2

The Scottish Government defines the Comparative Illness Factor (CIF) as an age- and sex-standardised ratio of observed to expected benefit claims. Version 2 stores the workbook's value on its published scale as `cif_ratio`. It removes the previous division by population. The existing percentile clipping, component weights and rounding still apply. Suppressed or missing measurements are omitted and the available weights are rescaled. `n_score_components` gives the number of inputs used for each zone. [SIMD technical notes, page 31](https://www.gov.scot/publications/simd-2020-technical-notes/)

The version 2 inputs used for the checked-in CSV had these SHA-256 hashes:

| Input | SHA-256 |
| --- | --- |
| `simd2020.csv` | `686bc9aa38b61891f701e10d8a3970397c7be7f3819798dc43584ae42cb3a391` |
| `simd2020_indicators.xlsx` | `a90b4078e1af13cf48d540f324defaa01effb9043af3ed2cb3d2f11eefc3e365` |

The change preserves all 746 zone IDs, 746 deprivation deciles and all other source components. Three zones have a suppressed CIF value. In total, 738 scores use five components and eight use three or four. Ward forecast values are byte-for-byte identical to the baseline.

Compared with [the version 1 artifact](https://github.com/yehorm14/fire-sight/blob/f33336b2e4c0b0ca6d853d973dd838941ffbb6ad/data-pipeline/output/glasgowzones.csv), 601 of 746 scores and 717 ranks changed. Changes range from −9 to +12 points. Ranks use the same competition ranking for ties. At the cutoff of rank 10 or better, seven zones remain, four leave and three enter.

| Example zone | Score before → after | Rank before → after |
| --- | --- | --- |
| `S01010048` (largest rise) | 51 → 63 | 266 → 99 |
| `S01010130` (largest fall) | 57 → 50 | 147 → 324 |

The 0–100 score is a heuristic vulnerability composite whose weights have yet to be validated against fire incidents. The rank changes describe sensitivity to the corrected CIF input.

## Ward forecast CSV migration

| Legacy column | Annual replacement |
| --- | --- |
| `history_6mo` | `history_annual` (up to six annual counts) |
| `forecast_6mo` | `forecast_1yr` |
| `forecast_12mo` | `forecast_2yr` |
| `forecast_18mo` | `forecast_3yr` |
| `forecast_lower`, `forecast_upper` | `forecast_lower_1yr`, `forecast_upper_1yr` |

The regenerated CSV also includes bounds for years two and three, each projected financial year, and the first and last observed financial years. The API can read the previous CSV. It preserves the annual counts and first-step bounds and reports the later bounds as unavailable until the CSV is regenerated. See the [API migration notes](../backend/README.md#ward-projections).

## Ward vulnerability lookup

The committed [Glasgow lookup](../data-pipeline/reference/datazone_ward_lookup.csv) uses the Scottish Government's [SIMD 2020v2 Data Zone Lookup workbook](https://www.gov.scot/publications/scottish-index-of-multiple-deprivation-2020v2-data-zone-look-up/), updated January 2025. The workbook is available under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). Contains public sector information licensed under the Open Government Licence v3.0.

The generator pins the workbook SHA-256 (`0a64937af60fb339a1be85cd2f65b6a3d410a38dc5b6c7f25a72ba2d7060a03e`), extracts `DZ` and `MMWcode` for Glasgow City, and verifies exact coverage of all 746 modeled 2011 DataZones and the codes and names of all 23 [ONS May 2024 ward boundaries](https://www.data.gov.uk/dataset/faf874fd-aee8-4ca0-a4a9-4c8885ba3e82/wards-may-2024-boundaries-uk-bgc) used by the app.

```bash
python data-pipeline/build_ward_lookup.py '/path/to/SIMD 2020v2 - datazone lookup - updated 2025.xlsx'
```

Each DataZone is assigned to one ward by the published lookup. The ward explorer uses the workbook’s `DZname` field with the stable 2011 DataZone code. The ward vulnerability score is the population-weighted mean of its assigned DataZone scores, with an unweighted mean when the ward has no positive population weights. Drivers use population-weighted frequency of the assigned DataZones' model drivers. The API reports unmatched zones and wards without scored zones at startup.

## Housing evidence

The [housing exposure audit](HOUSING_EXPOSURE_AUDIT.md) matches observed counts to dwelling stock, checks when each release was available, and records why the exploratory findings stay outside production forecasts.

## Limitations

- The "Mock" source, the premises overlay and the event markers are illustrative sample data.
- The model fits a recency-weighted linear trend to annual counts per ward. The residual range uses the point estimate ± 1.96 times the historical residual standard deviation, clipped at zero and rounded to whole counts. This describes historical fit error and has no calibrated coverage guarantee. The model has no weather, seasonality or planned-development inputs.
- Risk weights are chosen by hand and not validated against incident outcomes.
- If a ward has no scored DataZones available, the API may report a labelled SIMD-decile proxy. In model mode, sample population, planning and incident-history properties are excluded.
- Census 2022 and EPC data were planned but are not used.
