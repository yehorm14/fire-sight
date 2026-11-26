# Scottish best-fit ward dwelling-fire series

The [candidate CSV](../data-pipeline/reference/sfrs_best_fit_ward_dwelling_fires_fy2025_26.csv) contains **6,035 ward-year counts** for 355 wards, all 32 Scottish councils and the 17 financial years from FY2009/10 to FY2025/26. Glasgow has **391 rows** for 23 wards. The [release manifest](../data-pipeline/reference/sfrs_best_fit_ward_dwelling_fires_fy2025_26.manifest.json) records the source ID, download date, input and output hashes, geography, and validation results. The [direct Glasgow benchmark](../data-pipeline/reference/glasgow_ward_dwelling_fires.csv) remains a separate series through FY2022/23.

## Definition and geography

Count each SFRS incident row classified as `Dwelling Fire`, including all recorded accident statuses. The unit is **fires per ward per financial year**, from 1 April to 31 March. The date must agree with the workbook's financial-year label. Identical visible rows are counted separately because the public extract has no incident ID and the resulting counts reconcile to the published totals.

The fixed August 2026 Scottish Government lookup assigns each of 7,392 2022 DataZones to one electoral ward. Each incident inherits the whole-DataZone assignment across all 17 years. The Glasgow codes and names match the bundled May 2024 ward map (WD24), after trimming source whitespace. A DataZone that crosses a ward boundary can assign an incident to a different ward from its exact address. The resulting series also uses the latest revisions to past observations. [SFRS incident release](https://www.firescotland.gov.uk/publications/document/?id=9990) · [2022 DataZone lookup](https://data.gov.scot/dataset/2022_data_zone_lookup) · [ONS May 2024 ward boundaries](https://www.data.gov.uk/dataset/faf874fd-aee8-4ca0-a4a9-4c8885ba3e82/wards-may-2024-boundaries-uk-bgc)

## Coverage and overlap

- All **88,241** dwelling-fire rows map to a ward. There are zero missing or unknown councils, missing or unmatched DataZones, and disagreements between reported and lookup council codes or names.
- All **544** named council-year totals match the sum of the eight dwelling categories in `BuildingFiresLAData`. The workbook has one additional unnamed FY2024/25 row. Its eight dwelling counts are explicitly zero, so the builder records and excludes it. [SFRS Tables and Charts](https://www.firescotland.gov.uk/publications/document/?id=9989)
- The candidate includes **90 verified zero ward-year counts**. Each means that no qualifying published incident was assigned to that ward-year after council reconciliation. Missing geography or an unavailable published observation fails regeneration before any release is written. The builder has no missing-to-zero substitution for those failures.
- Glasgow's best-fit totals for FY2023/24, FY2024/25 and FY2025/26 are **689, 623 and 616**. Over the 322 ward-year cells shared with the direct series, **99** counts agree exactly, the mean absolute difference is **1.494 fires** and differences range from **−6 to +9**. The two Glasgow totals for the overlap are 13,530 best-fit and 13,525 direct. Keep the two source IDs distinct in evaluation.

The Scottish Fire and Rescue Service and the Scottish Government published the underlying data. Contains public sector information licensed under the [Open Government Licence 3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). [SFRS bulletin](https://www.firescotland.gov.uk/publications/document/?id=9994) · [Lookup licence](https://data.gov.scot/dataset/2022_data_zone_lookup)

## Regenerate or evaluate

Install `data-pipeline/requirements.txt`. Download the [30 October 2026 Fires Dataset](https://www.firescotland.gov.uk/publications/document/?id=9990), the [30 October 2026 Tables and Charts workbook](https://www.firescotland.gov.uk/publications/document/?id=9989), and the [19 August 2026 lookup CSV](https://data.gov.scot/dataset/2022_data_zone_lookup/resource/81b010f5-0207-4ee5-bd2d-e7821aa6a3dc). The manifest records the files retrieved on 26 November 2026. The builder uses exact SHA-256 checks, so a later publisher revision requires a separately versioned build.

Run from the repository root with the downloaded paths:

```bash
python data-pipeline/build_best_fit_ward_series.py \
  --incidents /path/to/sfrs-incident-workbook.xlsx \
  --lookup /path/to/2022-datazone-lookup.csv \
  --tables /path/to/sfrs-tables-workbook.xlsx
```

The builder defaults to `data-pipeline/reference/`. Use `--output-dir PATH` to write the CSV and manifest elsewhere for a byte-for-byte comparison.

The forecast evaluator selects Glasgow using the bundled map IDs. For other councils, filter the CSV by `CouncilCode` and keep `GeographyCode` and `DateCode` as the ward-year key.

```bash
python data-pipeline/evaluate_ward_forecasts.py \
  --fire-csv data-pipeline/reference/sfrs_best_fit_ward_dwelling_fires_fy2025_26.csv
```
