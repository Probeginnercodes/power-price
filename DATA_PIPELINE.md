# Reduced Project 5 — first data downloader

Python 3.10+. Dependencies: `entsoe-py`, `pandas`, `python-dotenv`, `requests`.

Place `download_data.py` beside your private `.env` containing `ENTSOE_API_TOKEN=...`. Never commit the token or datasets. The script also accepts `ENTSOE_API_KEY` as a fallback name. Do not paste tokens or authenticated URLs into chat.

```bash
python download_data.py --start 2026-10-15 --end 2026-10-22
python download_data.py --start 2026-10-15 --end 2026-10-22 --datasets prices load wind_solar
python -m unittest -v
```

End is exclusive in UTC. Native-resolution CSVs, unchanged raw response bodies, redacted request metadata and a manifest are stored in unique `data/downloads/<run-id>/` folders. Calls use weekly chunks and library retries. Negative prices are valid. A failed dataset produces a nonzero exit code and does not prevent the remaining requested datasets being attempted.

This is ingestion, not a modelling-ready feature pipeline. No filling, hourly averaging or asinh transformation is performed. Library parsing may normalise resolution; inspect raw XML and units before hourly aggregation. Observed timestamp spacing is not sufficient to establish completeness. No target-day actual generation or actual load is requested.

Availability caveat: historical forecasts can be revised. A document creation timestamp is preserved where available, but does not establish original publication or availability at the chosen auction cutoff. Populate the information-set table before using forecasts in a backtest.

Suggested learning order: `main()` arguments and dates, `archive_response()`, `clean_result()`, then manifest construction. First run prices only and inspect the files. The API token is used locally, never printed by this script.

Source for library methods: https://github.com/EnergieID/entsoe-py

## Prepare hourly data

`prepare_data.py` selects the newest successful download containing prices, load and wind/solar. It validates source resolution and units from archived metadata, demands complete timestamp grids and numeric values, and joins hourly tables by UTC timestamps. It averages equal-duration inputs without filling gaps. Native downloads are never changed.

```bash
python -m unittest -v
python prepare_data.py
# Or select a specific run:
python prepare_data.py --run-id 20261021T231249530385Z_af7e7839
```

Outputs are new `data/processed/<source-run>_<unique-id>/hourly.csv` and `validation.json` files. Negative prices remain valid; incomplete hours and negative load/generation forecasts fail validation. Mixed-resolution histories must be prepared in separate periods in this first version. Berlin local timestamps retain UTC offsets, so repeated clock hours are unambiguous. A UTC range can include partial local days; use complete local delivery days when building the forecasting backtest.

The October 15–22 UTC sample produced 168 hourly rows and the combined test suite passed 12 tests. Forecast publication/availability checks are still required before training. Hourly average prices are a research aggregation of shorter-interval products, not a separately traded hourly price. No asinh transformation or modelling is included yet.
