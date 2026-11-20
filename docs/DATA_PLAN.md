# RigMind data plan

Goal: run on **real public Alberta data** wherever it exists, and generate seeded data only for what public data cannot provide (users, private company documents, daily operations). Every number and every answer must be traceable to its source file.

## 1. Real data sources

| Source | Contents | Refresh | Goes into |
|---|---|---|---|
| Petrinex AB **Conventional Volumetric Data** | Per facility, per month: activity (PROD, FLARE, VENT, FUEL, DISP…), product (OIL, GAS, WATER, COND…), From/To well or facility, volume, energy, hours. 30 columns, ~530k rows/month. Current year + previous 4 years only. | Monthly | `stg_volumetric` → `production_monthly`, `facility_activity_monthly` |
| Petrinex AB **Well Infrastructure** | Well ID, licence, linked facility, field, pool, status, spud date, horizontal flag, confidential type | Monthly | `wells` |
| Petrinex AB **Well Licence** | Licence number, licensee, location, status | Monthly | `well_licences` |
| Petrinex AB **Well to Facility Link** | Well → facility link with start date | Monthly | `well_facility_links` |
| Petrinex AB **Business Associate** + code reports (Field, Activity, Product, Facility Subtype) | Operator names, code lookups | Daily/monthly | `operators`, `codes_*` |
| AER **ST37 List of Wells** | Well locations (surface/bottom hole) | Monthly | `wells.lat/lon` |
| AER **directives and manuals** (PDF) | Regulations for RAG | When AER publishes a new edition | `documents`, `chunks` |
| Optional later: Norway Sodir FactPages | Clean monthly production per field (CSV) | Monthly | Second region |

Download endpoints (tested 2026-11-18, no login needed):
- Volumetrics: `https://www.petrinex.gov.ab.ca/publicdata/API/Files/AB/Vol/{YYYY-MM}/CSV`
- Infrastructure: `https://www.petrinex.gov.ab.ca/publicdata/API/Files/AB/Infra/{name}/CSV` with name = `Well Infrastructure`, `Well Licence` (also tested). The same pattern is expected for `Business Associate`, `Facility Infrastructure`, `Well to Facility Link`, `Facility Licence`, `Facility Operator History` (not tested yet).
- Code lookups (plain CSV): `https://www.petrinex.gov.ab.ca/bbreports/PRAActivityCodes.csv`, `PRAFieldCodes.csv`, `PRAFieldandPoolCodes.csv`, `PRAFacilityCodes.csv`, `PRABAIdentifiers.csv` …

**First directives to ingest** (all link to the production data; confirm the current edition when downloading):
Directive 007 (volumetric and infrastructure requirements), Manual 011 (how to submit volumetric data), Directive 017 (measurement), Directive 060 (flaring, venting, incineration), Directive 013 (well suspension), Directive 020 (well abandonment), Directive 036 (drilling blowout prevention), Directive 071 (emergency preparedness).

Data and regulations link up: "Is well X flaring above the Directive 060 limits?" needs both, and is a strong demo for the agent.

## 2. Pipeline (raw → staging → clean → marts)

```
data/raw/petrinex/vol/2026-08.zip        (git-ignored, never committed)
   │  download task (Celery beat, monthly; manual CLI for now)
   ▼
stg_volumetric        all 30 columns as TEXT, + source_file, loaded_at   (COPY, no transforms)
   │  normalize (Python, idempotent)
   ▼
production_monthly    one row per well × month × product:
                      well_id, month, product, volume, hours, facility_id, source_file
facility_activity_monthly   facility × month × activity × product (flare/vent/fuel)
   │  SQL views / materialized views
   ▼
v_well_monthly (oil_m3, gas_e3m3, water_m3, cond_m3, hours, gor, water_cut)
mv_operator_monthly, mv_top_wells
```

Rules:
- Keep IDs as **text** (leading zeros matter; the layout guide warns about this).
- Masked confidential values (`***`) become NULL with an `is_masked` flag; never guess them.
- Upsert keyed on (well_id, month, product): rerunning a month replaces it, because Petrinex republishes amended months.
- Lineage on every row (source_file, submission_date), so data answers can cite "Petrinex Conventional Volumetrics, 2026-08".
- Units: liquids m³, gas 10³m³ (e3m3), energy GJ.
- Start with the last 24 months (see the size estimate below); go to 5 years once queries are indexed.

**Verified on the real August 2026 file (inspected 2026-11-18):**

| Fact | Value | What it means for the code |
|---|---|---|
| Packaging | **Zip inside a zip**: `Vol_2026-08-AB.csv.zip` → `Vol_2026-08-AB.CSV` | Open the inner zip from memory; never extract to disk |
| Size per month | 7.7 MB download, **120 MB CSV, 529,582 rows**, 30 columns, header row | Stream rows (`zipfile` + `io.TextIOWrapper` + `csv`), don't load the whole file |
| Quoting | Mostly unquoted, but ~1,800 rows/month have quoted commas (`"MEDICINE HAT, CITY OF"`) | Use the `csv` module; `line.split(",")` silently breaks rows |
| Well rows | `FromToIDType = "WI"`, `ActivityID = "PROD"`: 242k rows, **134,547 producing wells**, 42,567 with oil > 0 | This is `production_monthly` |
| Well ID | `ABWI100010206504W400` (= UWI 100/01-02-065-04W4/00) | Text key; matches `WellID` in Well Infrastructure **100%** (134,547 of 134,547) |
| Products on PROD rows | GAS 133k, WATER 62k, OIL 43k, COND 3.8k, small others | Pivot to oil_m3, gas_e3m3, water_m3, cond_m3 |
| Hours | Set on almost all OIL rows, blank on ~40% of GAS and most WATER rows | hours_on = max(Hours) across the well's products that month |
| Duplicates | 15 well × product keys appear twice (well reported at two facilities) | Sum volumes; keep both facility IDs |
| Masked values | `***` in FromToID 15,894 rows, Hours 1,899, Volume 11 | NULL + `is_masked`; exclude masked FromToID rows from well data |
| Other well activities | ROYALTY, VENT, SHUTIN, INJ, FUEL, FLARE, LD* | FLARE/VENT/FUEL → `facility_activity_monthly`; INJ for injection wells (later) |
| Amendments | Aug file has rows submitted in Sep (493k) and **Oct (35k)** | Re-download the last 3 months on every refresh and upsert |

| Infrastructure file | Size | Rows | Useful columns |
|---|---|---|---|
| Well Infrastructure | 67 MB zip, 296 MB CSV (zip in zip) | 681,928 | WellID, WellName, LicenceNumber, Field/FieldName, Area, PoolDeposit/Name, WellStatus*, SpudDate, HorizontalDrill, FinalTotalDepth, **LicenseeID, LicenseeName**, LinkedFacilityID, ConfidentialType |
| Well Licence | zip (size not measured) | 529,841 | LicenceNumber, LicenceIssueDate, LicenceStatus, LicenseeName, location, WellPurpose, WellSubstance, TargetPool, **OrphanWellFlg** |

Well Infrastructure already carries the licensee, so "production by company" does not need the facility operator (`OperatorBAID` in volumetrics is the *facility* operator).

**Database size estimate:** `production_monthly` (well × month × product) ≈ 240k rows per month → 24 months ≈ 5.8M rows; 5 years ≈ 14.5M. The pivoted view has ~135k well-months per month. Comfortable for Postgres with indexes on (well_id, month) and (month, product).

## 3. Download and load plan

1. **Where it runs:** a Python CLI in the repo, run locally or in the Django container. Raw zips go to `data/raw/petrinex/` (git-ignored).
   - `python -m petrinex.download vol --from 2024-09 --to 2026-08`
   - `python -m petrinex.download infra "Well Infrastructure" "Well Licence"`
   - `python -m petrinex.download codes`
   - Polite: one request at a time, retry with backoff, skip months already on disk unless `--force`. Log URL, bytes and SHA-256 of each file in `data/raw/petrinex/manifest.jsonl`.
2. **Parse:** `petrinex.read.iter_rows(zip_path)` yields typed rows (a dataclass per file) straight from the inner zip; the filter keeps well PROD rows and all FLARE/VENT/FUEL rows (these appear on well rows too: VENT 19k, FUEL 8.6k, FLARE 0.6k on `WI` in Aug 2026).
   - **Measured on Aug 2026 (2026-11-20):** 286,193 of 529,582 rows kept (54%): PROD 243,446, VENT 24,749, FUEL 14,932, FLARE 3,066; 774 kept rows masked (all in Hours). ~11 s, 51 MB peak memory. PROD only occurs on `WI` rows; Hours are whole numbers.
   - Distinct `FromToID` on PROD rows: 135,265 (oil > 0: 42,655). The 134,547 / 42,567 in §2 came from an earlier inspection with a definition that was not recorded; use the reader's numbers from now on.
3. **Load:** Django management command `load_petrinex --month 2026-08`: COPY filtered rows into `stg_volumetric`, then one SQL upsert into `production_monthly` (one row per well × month × product; `v_well_monthly` pivots it) inside a transaction. Rerunning a month replaces it.
4. **Refresh:** Celery beat, monthly: download the newest month + re-download the previous 3 (amendments) + infrastructure, then load.
5. **Tests:** fixtures are 50-row CSVs cut from the real files (masked rows, a quoted comma, a duplicate well, a blank-hours GAS row), zipped twice like the real thing. No network in tests.

## 4. Seeded data (what public data cannot give us)

All of it is reproducible (`random.Random(42)`), clearly labelled as fictional, and created by one command: `python manage.py seed_demo`.

| Seed | Why | How |
|---|---|---|
| **Demo company "Demo Energy Ltd."** with users per role (field_engineer, ops_manager, admin) | Auth, roles, demo login | Django management command |
| **"Our wells"**: the demo company's watchlist of ~50 *real* wells | The company story stays on real data | Pick wells from one real field |
| **Internal documents** (fictional SOPs, a well-work procedure, an incident report template), restricted to some roles | Tests that RAG filters by role: a field engineer must never see ops-manager-only content | Markdown → PDF, written by us |
| **Prompt-injection test PDF** ("ignore your instructions…") | Guardrail eval | Hand-written |
| **Daily operations log** for the 50 wells: downtime events, causes, maintenance work orders | Public data is monthly only; this enables "why did W123 drop in March?" | `data/generate_ops.py`: seeded, consistent with real monthly volumes (downtime only in months where hours_on dropped) |
| **Test fixtures**: small CSVs in the exact Petrinex layout with tricky rows (masked values, leading zeros, amended months) | Unit tests never hit the network | `tests/fixtures/petrinex/*.csv` |
| **Golden eval set** (30–50 questions) | Evals | Hand-written from the directives + answers computed from a frozen data snapshot |

## 5. Licences
Sources are credited on every page. Use of each dataset follows its publisher's terms (AER copyright notice; Petrinex ER Public Use Disclaimer). Raw source files are not redistributed from this repo.
