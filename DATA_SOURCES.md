# Rwanda rainfall data: sources and download method

Monthly rainfall (mm) for each of Rwanda's 30 districts and 5 provinces,
January 1981 to September 2026.

Last downloaded: 2026-10-06 (exact time and file checksums are in
`data/raw/download_log.json`, which the script rewrites on every run).

## Quick start

```bash
./venv/bin/pip install -r requirements.txt
./venv/bin/python get_rwanda_rainfall.py
```

The script downloads the raw files, writes the download log, and builds the
two monthly tables. Re-run it to get newer months. HDX updates the file about
every 14 days.

## Files

| File | What it is |
|---|---|
| `get_rwanda_rainfall.py` | Downloads and processes everything below |
| `data/raw/rwa-rainfall-subnat-full.csv` | Raw rainfall, 10-day (dekad) values per area, as downloaded |
| `data/raw/rwa_gazetteer_rphc2012_v2.xlsx` | Official names for the area codes, as downloaded |
| `data/raw/download_log.json` | Source URL, licence, HDX last-modified date, download time, size and SHA-256 for each raw file |
| `data/processed/rwanda_rainfall_district_monthly.csv` | **Main output.** 30 districts × 549 months = 16,470 rows |
| `data/processed/rwanda_rainfall_province_monthly.csv` | 5 provinces × 549 months = 2,745 rows |
| `rwanda_rainfall.ipynb` | Evaluation notebook: structure, plausibility, consistency checks, charts, and comparison with NASA POWER |
| `data/raw/nasa_power/` | Cached NASA POWER point responses used by the notebook (https://power.larc.nasa.gov/, `PRECTOTCORR`) |

Raw files are never edited. All changes happen in the script.

## Source 1: rainfall

- **Dataset:** Rwanda: Rainfall Indicators at Subnational Level
- **Page:** https://data.humdata.org/dataset/rwa-rainfall-subnational
- **File:** `rwa-rainfall-subnat-full.csv` (full time series. A second file
  `rwa-rainfall-subnat-5ytd.csv` has only the last five years.)
- **Published by:** WFP (UN World Food Programme) on HDX (Humanitarian Data Exchange)
- **Underlying data:** CHIRPS v2 (Climate Hazards Group InfraRed Precipitation
  with Station data), Climate Hazards Center, UC Santa Barbara,
  https://www.chc.ucsb.edu/data/chirps
- **Licence:** CC BY (Creative Commons Attribution)
- **Coverage:** 1981-01-01 onward, updated about every 14 days

### How it was made (by WFP, before we downloaded it)

CHIRPS combines satellite infrared estimates with rain-gauge readings on a grid
of about 5 km. WFP averaged the grid cells that fall inside each
province and district polygon, for each 10-day period (dekad). Each dekad is
dated by its first day: the 1st, 11th and 21st of the month. The `n_pixels`
column says how many grid cells went into each average.

WFP also gives a long-term average (`rfh_avg`) for each dekad, calculated over
**1989–2018**, and anomalies relative to it.

Each row has a `version`:
- `final`: the finished CHIRPS product
- `prelim`: early estimate for the most recent weeks, replaced by `final` later
- `forecast`: CHIRPS-GEFS forecast for the coming dekad (not observed rain)

## Source 2: district and province names

The rainfall file only has codes (e.g. `RW11`). Names come from:

- **Dataset:** Rwanda - Subnational Administrative Boundaries
- **Page:** https://data.humdata.org/dataset/cod-ab-rwa
- **File:** `rwa_gazetteer_rphc2012_v2.xlsx`, sheets `ADM1` (provinces) and
  `ADM2` (districts)
- **Published by:** National Institute of Statistics of Rwanda (NISR), on HDX
- **Licence:** CC BY-IGO

All 30 district codes and 5 province codes in the rainfall file matched this
list exactly.

## How the data was downloaded

Both files were fetched with the HDX CKAN API, not by clicking through the
website. That makes the download repeatable:

1. Ask HDX for the dataset's file list:
   `https://data.humdata.org/api/3/action/package_show?id=rwa-rainfall-subnational`
   (and `?id=cod-ab-rwa` for the names).
2. Find the file by name in the `resources` list and take its `url`.
3. Download that URL and save it unchanged to `data/raw/`.
4. Record the source, licence, URL, time, size and SHA-256 in
   `data/raw/download_log.json`.

The same files can be downloaded manually from the two dataset pages above.

## Processing steps (in `get_rwanda_rainfall.py`)

1. **Drop forecast rows.** Only `final` and `prelim` (observed) rows are kept.
2. **Merge Rusizi's two polygons.** In the raw file, Rusizi (`RW36`) appears
   twice for every date, as two separate shapes (`adm_id` 1011443 with 2
   pixels and 1011471 with 27 pixels). The small one is probably an island in
   Lake Kivu, but this has not been checked. Adding them up would double
   Rusizi's rainfall. They are combined into one value per dekad, weighting
   each part by its pixel count. No other area is split.
3. **Dekads to months.** The three dekads in each month are summed to give
   monthly rainfall (`rain_mm`). The long-term averages are summed the same
   way (`normal_mm`).
4. **Add names** from the NISR gazetteer.
5. **Flag quality:** `complete` (all 3 dekads present) and `preliminary` (any
   dekad not yet final).

`START_YEAR` at the top of the script can be set to 1986 (or any year) to
start the outputs later. The default is 1981, the first year available.

## Output columns

| Column | Meaning |
|---|---|
| `province_pcode`, `province` | Province code and English name |
| `district_pcode`, `district` | District code and English name (district file only) |
| `year`, `month_num`, `month` | Year, month 1–12, and `YYYY-MM` |
| `rain_mm` | Total rainfall that month, mm (average over the area) |
| `normal_mm` | Long-term average rainfall for that calendar month, mm, 1989–2018 baseline |
| `pct_of_normal` | `100 × rain_mm / normal_mm`. Below 100 is drier than usual |
| `n_dekads` | Dekads summed (3 = full month) |
| `complete` | `True` if all 3 dekads are present |
| `preliminary` | `True` if any dekad is still preliminary. Will be revised |
| `n_pixels` | CHIRPS grid cells averaged for the area |

## Checks done

- 30 districts and 5 provinces, each with 549 months (1981-01 to 2026-09)
- No missing values. Every month has all 3 dekads
- No duplicate area-dekad rows after merging Rusizi
- Only 2026-09 is preliminary
- Average annual rainfall 1991–2020 is lowest in the east (Nyagatare ≈ 930
  mm, Bugesera ≈ 937 mm) and highest in the southwest (Rusizi ≈ 1,427 mm,
  Nyamasheke ≈ 1,407 mm). Monthly averages show the two rainy seasons
  (March–May and September–December) and a dry June–August. Both match
  Rwanda's known climate.

## Limitations

- **Preliminary months change.** Rows with `preliminary = True` (currently
  2026-09) will be revised. Re-run the script or drop them before analysis.
- **Small districts have few pixels.** Nyarugenge (Kigali) is averaged
  from only 2 grid cells, so its values are less reliable than those for
  large districts (up to 62 cells).
- **Satellite estimate, not gauges.** CHIRPS is calibrated with station data,
  but Rwanda has few stations in the record, especially in the 1990s. Short,
  local storms may be under- or over-estimated.
- **Boundaries are the current ones.** Districts were created in 2006. Values
  for earlier years are rainfall over today's district areas, which is
  fine for rainfall but matters when joining to older data organised by
  prefecture or commune.
- **CHIRPS version.** This file uses CHIRPS v2. If WFP switches to a newer
  CHIRPS version, the whole series may change, so keep the download log.

## How to cite

> Funk, C. et al. (2015). The climate hazards infrared precipitation with
> stations—a new environmental record for monitoring extremes. *Scientific
> Data* 2, 150066. https://doi.org/10.1038/sdata.2015.66

> WFP (2026). Rwanda: Rainfall Indicators at Subnational Level. Humanitarian
> Data Exchange. https://data.humdata.org/dataset/rwa-rainfall-subnational
> (accessed 2026-10-06).

> NISR. Rwanda - Subnational Administrative Boundaries. Humanitarian Data
> Exchange. https://data.humdata.org/dataset/cod-ab-rwa (accessed 2026-10-06).
