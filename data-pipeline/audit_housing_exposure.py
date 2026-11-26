"""Audit public Glasgow housing aggregates against the versioned SFRS ward panel."""

import argparse
import csv
from datetime import date
from io import BytesIO, TextIOWrapper
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from openpyxl import load_workbook
import pandas as pd

from build_best_fit_ward_series import BASENAME, REFERENCE
from evaluate_ward_forecasts import sha256
from ward_forecasts import WARDS_GEOJSON, ward_observations

GLASGOW = "S12000049"
FIRST_ORIGIN, LAST_OBSERVATION = 2018, 2025
LEGACY_RELEASE = date(2024, 6, 20)
DZ2022_RELEASE = date(2025, 6, 26)
SOURCES = {
    "dwellings-estimates.xlsx": "d360c844269b6398064ba403f2da9ccd2ed112207c1b02e7b8c7d15869d77549",
    "household-estimates-2023-release.xlsx": "7f593709b026fc8bcb30943d4505857fe1772237c16ce5bd76a00c778148d40b",
    "electoral-wards-2024-release.zip": "bcccf9b309992d0830f6894e1da88905ec319d40ccbb620e3d067f106d138d86",
    "electoral-wards.zip": "8ac71f39decf5393615f1121d9f93998d8791ef93cd79ee6b6815f01d27863c6",
    "dwellings-estimate-by-2011-data-zones.xlsx": "6fdf2951223dd01e5790069d61428ce25d92aed5f260197ee546223113df4e49",
    "dwelling-estimates-by-2022-data-zones-24-25.xlsx": "5d61db5faf7e81451d838e5d394b8e0682bbf501341c1220aea4a78082ceb033",
    "household-estimates-by-2011-data-zones.xlsx": "4061bbba01790a7e25dfb1598ad46d47116ae911a91b7a3e708a9c8ba1ba4fe6",
    "household-estimates-by-2022-data-zones-24-25.xlsx": "c7e1df4c7964e2206668ba46d85002fceed93d7b38b881e8c220920abb337f5b",
    "census-2022-oa-univariate.zip": "6e1673bafa2d31a4342a767bb96872639697232706c0fa4cde5250da71afc58f",
    "census_2022_index.zip": "0e4096a321cba2318dc5d2e35c197bf815ac333aebdf4cb0ddce82112b57a261",
    "datazone-2022-lookup.csv": "41f51a4c0e6edbd30f81c3d8d79c37f3f557a3c1d887a10b75c07f0bc01e0891",
}
CENSUS_FIELDS = {
    "UV402": ("Flat, maisonette or apartment: Total",
              "Flat, maisonette or apartment: Purpose-built block of flats or tenement"),
    "UV404": ("Social Rented: Council (LA) or Housing Association/ Registered Social Landlord",
              "Private rented: Total"),
    "UV406": ("One person",),
    "UV407": ("No central heating",),
    "UV415": ("Occupancy rating of bedrooms: -1 or less",),
}


def eligible_origins(published):
    """Return matched rolling-origin leads whose stock release is already public."""
    return {
        origin: list(range(1, min(3, LAST_OBSERVATION - origin) + 1))
        for origin in range(FIRST_ORIGIN, LAST_OBSERVATION)
        if published <= date(origin + 1, 3, 31)
    }


def sheets(book):
    return sorted(int(name) for name in book.sheetnames if name.isdecimal())


def ward_workbook(archive_path, filename):
    with ZipFile(archive_path) as archive:
        member = next(name for name in archive.namelist() if name.endswith("/" + filename))
        return load_workbook(BytesIO(archive.read(member)), read_only=True, data_only=True)


def ward_values(book, year, wards):
    rows = [row for row in book[str(year)].values if row[0] in wards]
    if not rows:
        raise ValueError(f"No NRS ward stock rows in {year}")
    table = pd.DataFrame(rows, columns=range(len(rows[0]))).set_index(0).sort_index()
    if table.index.has_duplicates or set(table[1].str.strip().items()) != set(wards.items()):
        raise ValueError(f"NRS ward codes and names do not match the Glasgow map in {year}")
    if pd.to_numeric(table[2], errors="coerce").isna().any() or (table[2] <= 0).any():
        raise ValueError(f"Missing or non-positive ward stock in {year}")
    return table


def ward_sums(book, years, lookup, columns):
    """Report gaps and only aggregate complete years, never treating gaps as zero."""
    result, gaps = {}, {}
    for year in years:
        rows = [r for r in book[str(year)].values if r[2] == GLASGOW]
        ids = pd.Index([r[0] for r in rows], name="zone_id")
        if ids.has_duplicates or not ids.isin(lookup.index).all():
            raise ValueError(f"Duplicate or unjoined Glasgow stock key in {year}")
        table = pd.DataFrame([[r[col] for col in columns] for r in rows], index=ids, columns=columns)
        numeric = table.apply(pd.to_numeric, errors="coerce").reindex(lookup.index)
        incomplete = numeric.isna().any(axis=1) | numeric.lt(0).any(axis=1)
        if incomplete.any():
            gaps[year] = numeric.index[incomplete].tolist()
            continue
        result[year] = numeric.groupby(lookup).sum().sort_index()
    return result, gaps


def census_inventory(topics_path, geography_path, wards):
    with ZipFile(geography_path) as archive:
        geo_file = next(n for n in archive.namelist() if n.endswith("/OA_TO_HIGHER_AREAS.csv"))
        lookup = pd.read_csv(archive.open(geo_file), usecols=["OA2022", "CA2019", "EW2022"])
        ward_file = next(n for n in archive.namelist() if n.endswith("/Electoral Ward 2022 Lookup.csv"))
        names = pd.read_csv(archive.open(ward_file), index_col="ElectoralWard2022Code")
        if names.loc[list(wards), "ElectoralWard2022Name"].str.strip().to_dict() != wards:
            raise ValueError("Census and map ward names differ")
    lookup = lookup.loc[lookup["CA2019"].eq(GLASGOW)].set_index("OA2022")["EW2022"]
    if lookup.index.has_duplicates or set(lookup) != set(wards):
        raise ValueError("Census Output Area mapping does not cover the Glasgow ward set")
    fields = {}
    with ZipFile(topics_path) as topics:
        for table, categories in CENSUS_FIELDS.items():
            filename = next(n for n in topics.namelist() if n.startswith(table + " "))
            with TextIOWrapper(topics.open(filename), encoding="utf-8-sig") as stream:
                reader = csv.reader(stream)
                header = [cell.strip() for cell in [next(reader) for _ in range(4)][3]]
                rows = [r for r in reader if r and r[0] in lookup.index]
            records = pd.DataFrame(rows, columns=header).set_index("")
            if records.index.has_duplicates or set(records.index) != set(lookup.index):
                raise ValueError(f"Census table {table} does not cover all joined Output Areas")
            for column in (header[1], *categories):
                values = pd.to_numeric(records[column], errors="coerce")
                unusable = values.isna() | values.lt(0)
                fields[f"{table} {column}"] = {
                    "unavailable_output_areas": int(unusable.sum()),
                    "unavailable_wards": int(lookup.loc[values.index[unusable]].nunique()),
                }
    return {"output_areas": len(lookup), "wards": len(wards), "fields": fields}


def profiled_poisson(counts, years, target, stock=None, target_stock=None, feature=None, target_feature=None):
    """Fit ward intercepts and a shared slope with an optional offset and time-varying feature."""
    counts, years = np.asarray(counts, dtype=float), np.asarray(years)
    shape = counts.shape
    if (counts.ndim != 2 or shape[1] < 2 or years.shape != (shape[1],)
            or not (np.diff(years) > 0).all() or target <= years[-1]
            or not np.isfinite(counts).all() or (counts < 0).any()
            or (counts % 1 != 0).any() or not counts.any()):
        raise ValueError("Expected observations for at least two growing years and a future target")
    stock = np.ones(shape) if stock is None else np.asarray(stock, dtype=float)
    target_stock = np.ones(shape[0]) if target_stock is None else np.asarray(target_stock, dtype=float)
    if (shape != stock.shape or target_stock.shape != (shape[0],)
            or not np.isfinite(stock).all() or not np.isfinite(target_stock).all()
            or (stock <= 0).any() or (target_stock <= 0).any()):
        raise ValueError("Poisson exposure requires a complete positive stock panel")
    time = (years - years[-1]) / 10
    fields = [np.broadcast_to(time, shape)]
    future_fields = [np.full(shape[0], (target - years[-1]) / 10)]
    if feature is not None:
        feature, target_feature = np.asarray(feature), np.asarray(target_feature)
        if (feature.shape != shape or target_feature.shape != (shape[0],)
                or not np.isfinite(feature).all() or not np.isfinite(target_feature).all()
                or np.equal(feature, feature[:, :1]).all()):
            raise ValueError("Expected a finite feature with within-ward variation")
        mean, std = float(feature.mean()), float(feature.std())
        fields.append((feature - mean) / std)
        future_fields.append((target_feature - mean) / std)
    predictors = np.stack(fields, axis=-1)
    future = np.stack(future_fields, axis=-1)
    totals = counts.sum(axis=1)
    offset = np.log(stock)
    beta = np.zeros(len(fields))
    for _ in range(100):
        weights = offset + predictors @ beta
        maximum = weights.max(axis=1, keepdims=True)
        exp_weights = np.exp(weights - maximum)
        sum_weights = exp_weights.sum(axis=1, keepdims=True)
        probabilities = exp_weights / sum_weights
        mean_features = (probabilities[..., None] * predictors).sum(axis=1, keepdims=True)
        centered = predictors - mean_features
        gradient = np.einsum("ij,ijk->k", counts, centered)
        information = np.einsum("i,ij,ijk,ijl->kl", totals, probabilities, centered, centered)
        step = np.linalg.solve(information, gradient)
        if np.max(np.abs(step)) < 1e-10:
            normalizer = maximum[:, 0] + np.log(sum_weights[:, 0])
            return totals * target_stock * np.exp(future @ beta - normalizer)
        beta += step
    raise ValueError("Poisson fit did not converge")


def ranking(series, limit=5):
    ordered = series.sort_index().sort_values(ascending=False, kind="stable")
    return ordered.head(limit).index.tolist()


def metrics(observed, forecasts):
    predicted = pd.Series(np.rint(forecasts).astype(int), index=observed.index)
    error = predicted - observed
    highest = ranking(predicted)
    return {
        "cases": len(error),
        "mae": round(float(error.abs().mean()), 4),
        "rmse": round(float(np.sqrt(np.square(error).mean())), 4),
        "bias": round(float(error.mean()), 4),
        "glasgow_forecast": int(predicted.sum()),
        "glasgow_error": int(error.sum()),
        "top_five": highest,
        "observed_fires_in_top_five": int(observed.loc[highest].sum()),
    }


def evaluate(counts, stock, vacancies):
    """Audit the one eligible one-year historical case with the archive known at origin."""
    origin = max(eligible_origins(LEGACY_RELEASE))
    last_stock = max(y for y in stock if y < LEGACY_RELEASE.year)
    observed = counts[origin + 1]
    years = [y for y in counts.columns if y < origin and y in stock] + [origin]
    exposure = pd.DataFrame({y: stock[min(y, last_stock)][4] for y in years})
    target_exposure = stock[last_stock][4]
    full_years = [y for y in counts.columns if y <= origin]
    scope = {
        "origin": origin,
        "target": origin + 1,
        "stock_snapshot_for_origin_year_and_target": last_stock,
        "matched_training_years": years,
        "counts_only_full_history": metrics(
            observed, profiled_poisson(counts[full_years], full_years, origin + 1),
        ),
        "counts_only": metrics(observed, profiled_poisson(counts[years], years, origin + 1)),
        "exposure": metrics(
            observed, profiled_poisson(counts[years], years, origin + 1, exposure, target_exposure),
        ),
    }
    vacancy_years = [y for y in years if y >= min(vacancies)]
    last_vacancy = max(y for y in vacancies if y < LEGACY_RELEASE.year)
    shares = pd.DataFrame({y: vacancies[min(y, last_vacancy)][6] / vacancies[min(y, last_vacancy)][4]
                           for y in vacancy_years})
    scope["vacancy_training_years"] = vacancy_years
    scope["vacancy_counts_only"] = metrics(
        observed, profiled_poisson(counts[vacancy_years], vacancy_years, origin + 1),
    )
    scope["vacancy_window_exposure_only"] = metrics(
        observed, profiled_poisson(counts[vacancy_years], vacancy_years, origin + 1,
                                    exposure[vacancy_years], target_exposure),
    )
    scope["exposure_plus_vacancy"] = metrics(
        observed, profiled_poisson(counts[vacancy_years], vacancy_years, origin + 1,
                                    exposure[vacancy_years], target_exposure, shares, shares[origin]),
    )
    return scope


def audit(raw):
    for filename, expected in SOURCES.items():
        if sha256(raw / filename) != expected:
            raise ValueError(f"{filename} does not match the pinned publication")
    fire_csv = REFERENCE / f"{BASENAME}.csv"
    fire_digest = sha256(fire_csv)
    manifest = json.loads(fire_csv.with_suffix(".manifest.json").read_text())
    if fire_digest != manifest["artifact"]["sha256"]:
        raise ValueError("Fire counts do not match the published manifest")
    ward_features = json.loads(WARDS_GEOJSON.read_text())["features"]
    wards = {item["properties"]["ward_id"]: item["properties"]["ward_name"] for item in ward_features}
    observed = ward_observations(pd.read_csv(fire_csv), set(wards))
    counts = observed.pivot(index="FeatureCode", columns="DateCode", values="Value").sort_index(axis=1)
    counts.columns = [int(label.split("/")[0]) for label in counts]
    lookup = pd.read_csv(REFERENCE / "datazone_ward_lookup.csv", index_col="datazone_id")["ward_id"]
    lookup22 = pd.read_csv(raw / "datazone-2022-lookup.csv", encoding="cp1252",
                           usecols=["LA_Code", "DZ22_Code", "MMWard_Code"])
    lookup22 = lookup22.loc[lookup22["LA_Code"].eq(GLASGOW)].set_index("DZ22_Code")["MMWard_Code"]
    if lookup.index.has_duplicates or lookup22.index.has_duplicates or set(lookup) != set(wards) or set(lookup22) != set(wards):
        raise ValueError("Published DataZone mappings must have unique keys and cover the map")

    old_stock = load_workbook(raw / "dwellings-estimates.xlsx", read_only=True, data_only=True)
    old_homes = load_workbook(raw / "household-estimates-2023-release.xlsx", read_only=True, data_only=True)
    archive_stock, stock_gaps = ward_sums(old_stock, sheets(old_stock), lookup, [4])
    vacancies, vacancy_gaps = ward_sums(old_homes, sheets(old_homes), lookup, [4, 6])
    if vacancy_gaps:
        raise ValueError(f"Missing historic vacancy source data in {sorted(vacancy_gaps)}")

    current_zip = raw / "electoral-wards.zip"
    current_stock = ward_workbook(current_zip, "dwellings-electoral-wards-24-25-2022DZ.xlsx")
    current_homes = ward_workbook(current_zip, "hh-electoral-wards-24-25-2022DZ.xlsx")
    older_zip = raw / "electoral-wards-2024-release.zip"
    older_2011 = ward_workbook(older_zip, "dwellings-electoral-wards-24-2011-based-tabs.xlsx")
    older_2022 = ward_workbook(older_zip, "dwellings-electoral-wards-24-2022-based-tabs.xlsx")

    # Confirm both recent stock denominators against the exact DataZone→ward
    # mapping used to create the versioned SFRS numerator.
    current22 = load_workbook(raw / "dwelling-estimates-by-2022-data-zones-24-25.xlsx",
                              read_only=True, data_only=True)
    totals22, gaps22 = ward_sums(current22, sheets(current22), lookup22, [4])
    if gaps22:
        raise ValueError(f"Missing Glasgow 2022 DataZone stock in {sorted(gaps22)}")

    retrospective = {}
    for year in sheets(current_stock):
        direct = ward_values(current_stock, year, wards)[2]
        if not direct.eq(totals22[year][4]).all():
            raise ValueError(f"Published ward stock differs from the #46 DataZone assignment in {year}")
        occupied = ward_values(current_homes, year, wards)[3]
        if pd.to_numeric(occupied, errors="coerce").isna().any() or (occupied <= 0).any():
            raise ValueError(f"Missing ward household coverage in {year}")
        fires = counts[year]
        rates = fires / direct * 1000
        ranking_counts, ranking_rates = ranking(fires), ranking(rates)
        retrospective[year] = {
            "fires": int(fires.sum()),
            "december_dwellings": int(direct.sum()),
            "september_occupied_dwellings": int(occupied.sum()),
            "fires_per_1000_december_dwellings": round(float(fires.sum() / direct.sum() * 1000), 4),
            "count_top_five": [wards[key] for key in ranking_counts],
            "rate_top_five": [wards[key] for key in ranking_rates],
            "top_five_overlap": len(set(ranking_counts) & set(ranking_rates)),
            "ward_data": [
                {"ward": wards[key], "fires": int(fires[key]), "dwellings": int(direct[key]),
                 "rate": round(float(rates[key]), 4)}
                for key in fires.index
            ],
        }
    older_2011_2024 = None
    for year in sheets(older_2011):
        stock = ward_values(older_2011, year, wards)[2]
        if year == 2024:
            older_2011_2024 = stock
    if older_2011_2024 is None:
        raise ValueError("Expected the 2024 stock in both DataZone editions")
    older_2022_2024 = ward_values(older_2022, 2024, wards)[2]
    newer_2022_2024 = ward_values(current_stock, 2024, wards)[2]
    edition_delta = older_2022_2024 - older_2011_2024
    legacy_current = {}
    for filename in ("dwellings-estimate-by-2011-data-zones.xlsx", "household-estimates-by-2011-data-zones.xlsx",
                     "household-estimates-by-2022-data-zones-24-25.xlsx"):
        book = load_workbook(raw / filename, read_only=True, data_only=True)
        legacy_current[filename] = sheets(book)

    return {
        "source_sha256": {
            **SOURCES,
            fire_csv.name: fire_digest,
            WARDS_GEOJSON.name: sha256(WARDS_GEOJSON),
            "datazone_ward_lookup.csv": sha256(REFERENCE / "datazone_ward_lookup.csv"),
        },
        "glasgow_ward_count": len(wards),
        "datazones_by_edition": {"2011": len(lookup), "2022": len(lookup22)},
        "available_sheets": {
            **legacy_current,
            "archived_2011_datazone_stock": sheets(old_stock),
            "archived_2011_datazone_occupancy": sheets(old_homes),
            "archived_2011_based_ward_stock": sheets(older_2011),
            "archived_2022_based_ward_stock": sheets(older_2022),
            "current_2022_datazone_stock": sheets(current22),
            "current_2022_based_ward_stock": sheets(current_stock),
            "current_2022_based_ward_occupancy": sheets(current_homes),
        },
        "archived_december_stock_missing_zones": stock_gaps,
        "change_in_december_2024_across_datazone_editions": {
            "wards_changed": int(edition_delta.ne(0).sum()),
            "largest_absolute_ward_change": int(edition_delta.abs().max()),
            "glasgow_total_change": int(edition_delta.sum()),
        },
        "ward_values_revised_after_2024_release": int(older_2022_2024.ne(newer_2022_2024).sum()),
        "retrospective": retrospective,
        "census_2022": census_inventory(raw / "census-2022-oa-univariate.zip", raw / "census_2022_index.zip", wards),
        "eligible_2022_datazone_stock_origins": eligible_origins(DZ2022_RELEASE),
        "legacy_2011_datazone_sensitivity": evaluate(counts, archive_stock, vacancies),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path, help="directory containing the pinned source files")
    args = parser.parse_args()
    print(json.dumps(audit(args.raw), indent=2))


if __name__ == "__main__":
    main()
