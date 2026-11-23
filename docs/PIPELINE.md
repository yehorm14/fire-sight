# Data pipeline

`data-pipeline/run_model.py` scores each Glasgow DataZone from five SIMD 2020 indicators (area deprivation decile, overcrowding, comparative illness factor, no central heating, crime rate) with fixed weights. It also fits a recency-weighted linear trend to yearly SFRS dwelling-fire counts for the 23 wards in `backend/data/glasgow_wards.geojson` and projects each of the first three financial years after the last observation. The committed data use 2009/2010 through 2022/2023, so the projected years are 2023/2024, 2024/2025 and 2025/2026. Each value is one financial year's dwelling-fire count. `notebook.ipynb` is an exploratory prototype with separate sample half-year logic.

The processed output is committed in `data-pipeline/output/`, so the API runs without the raw data. The raw inputs are not in git (the fire statistics file is about 12 MB).

## Regenerate the output

Raw inputs are not committed, so you must download them before `run_model.py` will work. `download_datasets.py` fetches the SIMD 2020v2 indicator workbook (`raw/simd2020_indicators.xlsx`) and the [SFRS fire statistics](https://data.gov.scot/dataset/fire___type_of_incident) (`raw/fire_statistics_scotland.csv`) into `data-pipeline/raw/`, which is gitignored. It skips files that already exist.

```bash
python data-pipeline/download_datasets.py
python data-pipeline/run_model.py
```

The downloader fetches the SIMD 2020v2 indicator workbook and the SFRS fire statistics, and exits non-zero if either fails. `data-pipeline/raw/simd2020.csv` (SIMD ranks and deciles per DataZone) is a manual step: save it from the Scottish Government SIMD 2020 page, as the script prints. `--boundaries` also downloads data zone boundaries (needs geopandas).

To regenerate only the ward projection CSV, run `python data-pipeline/ward_forecasts.py` with the SFRS CSV in place. Each ward must have consecutive, unique financial-year observations.

## Review regenerated data

`data-pipeline/output/manifest.json` records the sources, financial-year range and a SHA-256 for each committed CSV. CI runs `python backend/data_contract.py` (and the same checks inside pytest), so no download is needed. It checks required columns, one forecast per ward in `glasgow_wards.geojson`, annual financial-year labels for each lead (`2023/2024`, not month bins), ordered bounds, and that the CSVs still match the manifest.

When upstream inputs change:

1. Run the regeneration steps above.
2. `python backend/data_contract.py --write-manifest` (refuses to write if the contract fails).
3. Review the `git diff` of both CSVs and the manifest (ward counts, projected years, large forecast moves) and update test expectations that name specific years or counts.

## Ward forecast CSV migration

| Legacy column | Annual replacement |
| --- | --- |
| `history_6mo` | `history_annual` (up to six annual counts) |
| `forecast_6mo` | `forecast_1yr` |
| `forecast_12mo` | `forecast_2yr` |
| `forecast_18mo` | `forecast_3yr` |
| `forecast_lower`, `forecast_upper` | `forecast_lower_1yr`, `forecast_upper_1yr` |

The regenerated CSV also includes bounds for years two and three, each projected financial year, and the first and last observed financial years. The API can read the previous CSV. It preserves the annual counts and first-step bounds and reports the later bounds as unavailable until the CSV is regenerated. See the [API migration notes](../backend/README.md#ward-projections).

## Limitations

- The "Mock" source, the premises overlay and the event markers are illustrative sample data.
- The model fits a recency-weighted linear trend to annual counts per ward. The residual range uses the point estimate ± 1.96 times the historical residual standard deviation, clipped at zero and rounded to whole counts. This describes historical fit error and has no calibrated coverage guarantee. The model has no weather, seasonality or planned-development inputs.
- Risk weights are chosen by hand and not validated against incident outcomes.
- In "Model" mode a ward's score is the average DataZone score for its SIMD decile.
- Census 2022 and EPC data were planned but are not used.
