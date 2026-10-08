"""Download Rwanda rainfall (CHIRPS, via WFP/HDX) and build monthly
district and province tables.

Run from the project folder:
    ./venv/bin/python get_rwanda_rainfall.py

See DATA_SOURCES.md for what each file is and where it comes from.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

HDX_API = "https://data.humdata.org/api/3/action/package_show?id="

# Rainfall: "Rwanda: Rainfall Indicators at Subnational Level" (CHIRPS, by WFP)
RAIN_DATASET = "rwa-rainfall-subnational"
RAIN_FILE = "rwa-rainfall-subnat-full.csv"

# Names for the PCODEs: "Rwanda - Subnational Administrative Boundaries" (NISR)
NAMES_DATASET = "cod-ab-rwa"
NAMES_FILE = "rwa_gazetteer_rphc2012_v2.xlsx"

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed")
LOG_FILE = RAW_DIR / "download_log.json"

# Set to e.g. 1986 to drop earlier years from the outputs. The raw file is
# always kept whole.
START_YEAR = 1981


def find_resource(dataset, file_name):
    """Ask the HDX API for a dataset's files and return the one we want."""
    info = requests.get(HDX_API + dataset, timeout=60)
    info.raise_for_status()
    result = info.json()["result"]
    for res in result["resources"]:
        if res["name"] == file_name:
            return result, res
    names = [res["name"] for res in result["resources"]]
    raise SystemExit(f"{file_name} not found in {dataset}. Files: {names}")


def download(dataset, file_name):
    """Download one HDX file into data/raw and record where it came from."""
    result, res = find_resource(dataset, file_name)
    print("Downloading", res["url"])
    response = requests.get(res["url"], timeout=300)
    response.raise_for_status()

    path = RAW_DIR / file_name
    path.write_bytes(response.content)

    return {
        "file": str(path),
        "dataset_title": result["title"],
        "dataset_page": f"https://data.humdata.org/dataset/{result['name']}",
        "source": result.get("dataset_source"),
        "license": result.get("license_title"),
        "dataset_date_range": result.get("dataset_date"),
        "hdx_last_modified": result.get("last_modified"),
        "download_url": res["url"],
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "size_bytes": len(response.content),
        "sha256": hashlib.sha256(response.content).hexdigest(),
    }


def load_names(path):
    """PCODE -> English name table for provinces (adm 1) and districts (adm 2)."""
    adm1 = pd.read_excel(path, sheet_name="ADM1")
    adm2 = pd.read_excel(path, sheet_name="ADM2")
    provinces = adm1[["ADM1_PCODE", "ADM1_EN"]].rename(
        columns={"ADM1_PCODE": "province_pcode", "ADM1_EN": "province"}
    )
    districts = adm2[["ADM2_PCODE", "ADM2_EN", "ADM1_PCODE"]].rename(
        columns={
            "ADM2_PCODE": "district_pcode",
            "ADM2_EN": "district",
            "ADM1_PCODE": "province_pcode",
        }
    )
    districts = districts.merge(provinces, on="province_pcode")
    return provinces, districts


def merge_split_areas(df):
    """Some areas come as several polygons (Rusizi has two adm_ids). Combine
    them into one row per PCODE and dekad, weighting each part by its pixels."""
    df = df.copy()
    df["w_rfh"] = df["rfh"] * df["n_pixels"]
    df["w_avg"] = df["rfh_avg"] * df["n_pixels"]
    out = df.groupby(["adm_level", "PCODE", "date"], as_index=False).agg(
        w_rfh=("w_rfh", "sum"),
        w_avg=("w_avg", "sum"),
        n_pixels=("n_pixels", "sum"),
        n_parts=("adm_id", "nunique"),
        version=("version", lambda v: "final" if (v == "final").all() else "prelim"),
    )
    out["rfh"] = out["w_rfh"] / out["n_pixels"]
    out["rfh_avg"] = out["w_avg"] / out["n_pixels"]
    return out.drop(columns=["w_rfh", "w_avg"])


def to_monthly(df):
    """Sum the three 10-day (dekad) values in each month for each area."""
    df = df.copy()
    df["month"] = df["date"].dt.to_period("M").dt.to_timestamp()
    monthly = df.groupby(["PCODE", "month"], as_index=False).agg(
        rain_mm=("rfh", "sum"),
        normal_mm=("rfh_avg", "sum"),
        n_dekads=("rfh", "count"),
        n_pixels=("n_pixels", "first"),
        preliminary=("version", lambda v: (v != "final").any()),
    )
    # Rainfall as a percentage of the long-term average for that month
    monthly["pct_of_normal"] = (100 * monthly["rain_mm"] / monthly["normal_mm"]).round(1)
    # A full month has 3 dekads. Incomplete months are only at the very end.
    monthly["complete"] = monthly["n_dekads"] == 3
    monthly["year"] = monthly["month"].dt.year
    monthly["month_num"] = monthly["month"].dt.month
    monthly["month"] = monthly["month"].dt.strftime("%Y-%m")
    for col in ["rain_mm", "normal_mm"]:
        monthly[col] = monthly[col].round(1)
    return monthly


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    log = [download(RAIN_DATASET, RAIN_FILE), download(NAMES_DATASET, NAMES_FILE)]
    LOG_FILE.write_text(json.dumps(log, indent=2))
    print("Saved", LOG_FILE)

    # HDX files sometimes have a second row of '#' tags. Drop it if present.
    df = pd.read_csv(RAW_DIR / RAIN_FILE, dtype={"PCODE": str, "version": str})
    df = df[~df["date"].astype(str).str.startswith("#")].copy()
    df["date"] = pd.to_datetime(df["date"])
    for col in ["rfh", "rfh_avg", "n_pixels", "adm_level"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["date"].dt.year >= START_YEAR]

    # Keep observations only. Forecast rows (CHIRPS-GEFS) are not rainfall
    # that fell, and they get replaced by prelim/final data later.
    print("Version values:", df["version"].value_counts().to_dict())
    df = df[df["version"] != "forecast"]

    split = df.groupby("PCODE")["adm_id"].nunique()
    print("Areas split into several polygons (merged):", split[split > 1].to_dict())
    df = merge_split_areas(df)
    assert not df.duplicated(["adm_level", "PCODE", "date"]).any()

    print("Date range:", df["date"].min().date(), "to", df["date"].max().date())

    provinces, districts = load_names(RAW_DIR / NAMES_FILE)
    cols = ["year", "month_num", "month", "rain_mm", "normal_mm", "pct_of_normal",
            "n_dekads", "complete", "preliminary", "n_pixels"]

    # Districts (admin level 2)
    dist = to_monthly(df[df["adm_level"] == 2])
    dist = dist.rename(columns={"PCODE": "district_pcode"}).merge(
        districts, on="district_pcode", how="left", validate="many_to_one"
    )
    assert dist["district"].notna().all(), "Unmatched district PCODE"
    dist = dist[["province_pcode", "province", "district_pcode", "district"] + cols]
    dist = dist.sort_values(["district_pcode", "month"])

    # Provinces (admin level 1)
    prov = to_monthly(df[df["adm_level"] == 1])
    prov = prov.rename(columns={"PCODE": "province_pcode"}).merge(
        provinces, on="province_pcode", how="left", validate="many_to_one"
    )
    assert prov["province"].notna().all(), "Unmatched province PCODE"
    prov = prov[["province_pcode", "province"] + cols]
    prov = prov.sort_values(["province_pcode", "month"])

    dist_file = OUT_DIR / "rwanda_rainfall_district_monthly.csv"
    prov_file = OUT_DIR / "rwanda_rainfall_province_monthly.csv"
    dist.to_csv(dist_file, index=False)
    prov.to_csv(prov_file, index=False)

    print(f"Saved {dist_file}: {dist['district'].nunique()} districts, "
          f"{dist['month'].min()} to {dist['month'].max()}, {len(dist)} rows")
    print(f"Saved {prov_file}: {prov['province'].nunique()} provinces, {len(prov)} rows")
    print("Incomplete months:", sorted(dist.loc[~dist["complete"], "month"].unique()))
    print("Preliminary months:", sorted(dist.loc[dist["preliminary"], "month"].unique()))


if __name__ == "__main__":
    main()
