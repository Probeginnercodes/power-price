# Power Forecast Lab — reduced Project 5

**Question:** How accurately and with what uncertainty can DE-LU day-ahead prices be forecast from information available before the auction, and how does forecast quality affect constrained battery value?

**Success test:** On a predeclared untouched evaluation period with verified input vintages, LightGBM must beat LEAR on mean pinball loss, meet the declared interval-calibration target, and report point accuracy against naive plus battery value under matched costs and constraints.

**Timing disclosure:** These sentences were consolidated into this README after development and data inspection began; they were not saved here on day one. We cannot retroactively satisfy that timing requirement. `research_protocol.json` records the current protocol honestly; the final holdout is not assigned or certified untouched.

This is a local research application, not a trading service. Demo mode uses artificial data. Historical mode is exploratory because original input forecast vintages remain unverified. Acknowledging this limitation never certifies publication timing.

## Historical results — negative findings included

Source experiment: `20261024T170430888686Z_empirical_b972e4`. Delivery days: **15–21 October 2026**, 168 hourly forecasts. Training: trailing **364 calendar days**, with fewer usable days after explicit missing/DST exclusions. These dates have been inspected and must not be reused as a final untouched holdout.

| Model | MAE EUR/MWh | RMSE EUR/MWh | Mean pinball EUR/MWh | 80% coverage | Battery net EUR | Upper-bound capture |
|---|---:|---:|---:|---:|---:|---:|
| LEAR-style | 39.97 | 46.42 | 8.72 | 67.3% | 2,210.49 | 88.3% |
| LightGBM | 30.48 | 37.08 | 11.74 | 44.0% | 2,065.83 | 82.6% |
| Yesterday naive | **27.30** | **34.25** | — | — | 1,976.55 | 79.0% |
| Perfect foresight | — | — | — | — | 2,502.18 | 100.0% |

**We did not beat the naive benchmark on point accuracy.** LightGBM beat LEAR on MAE but lost on pinball loss. Neither model achieved nominal 80% interval coverage. The predictive success test is **NOT MET**. Better battery value than naive is a separate finding; it does not reverse the accuracy result.

The historical DM statistic is about 2.75 with raw p≈0.033 over only seven matched daily absolute losses. This is a short-sample diagnostic, not persuasive significance evidence. It is not a test of the primary pinball objective. No final significance claim is made.

## Leakage checklist

Software checks below exist and pass; unchecked evidence must not be represented as complete.

- [x] Use ENTSO-E day-ahead load/wind/solar forecasts, rather than actual generation as predictive inputs.
- [x] Align timestamp identities in UTC; keep Berlin delivery dates and offsets explicit.
- [x] Reject duplicate/naive timestamps; explicitly handle incomplete and 23/25-hour days, including lag sources.
- [x] Construct price profiles at local-calendar lags 1, 2 and 7; same-hour lag 3; target-day prices are not features.
- [x] Train on earlier delivery days; refit daily using the trailing calendar window.
- [x] Select LASSO alpha on a chronological segment inside training; preserve candidate scores for new fits.
- [x] Fit each scaler and asinh transform on its own training split; never fit them on evaluation outcomes.
- [x] Test that changing held-out actual prices does not change forecasts.
- [x] Retain raw quantile predictions; apply predeclared sorting without reference to outcomes.
- [x] Plan battery decisions using forecasts and settle them separately at actual prices; use identical physical settings for perfect foresight.
- [ ] Verify the exact historic auction cutoff and original publication/revision evidence for every input value, including all four load/wind/solar forecast columns.
- [ ] Verify original-vintage provenance for lagged auction-price profiles; delivery timestamps alone do not prove publication time.
- [ ] Assign and freeze a longer final holdout before fetching/inspecting its outcomes; do not tune on the inspected week.
- [ ] Recover any unarchived human experiments or disclose that their count is unknown.

`information_set.py` uses an assumed D−1 11:00 Berlin research cutoff; that assumption is not claimed to be the verified market gate. Receipt time/document creation time is not automatically the original publication time. The command `python run_pipeline.py --mode empirical --acknowledge-unverified-vintages --require-verified-vintages` deliberately **fails** until original-vintage evidence is available. The ordinary acknowledged empirical command remains explicitly exploratory.

## Trial accounting and selection

Archive inventory at 2026-10-24T19:08:13.560496+00:00: **12 executions**, **0 recorded failures**, **2 distinct saved model-configuration signatures**, and **5 unique empirical test signatures with available DM p-values. These categories are not interchangeable. Code-only changes can conservatively split test signatures; repeated identical tests are deduplicated for adjustment. **The lifetime number of human model trials is unknown.** No earlier trials are invented or silently assumed absent.

`research_audit.py` exports `data/research/trial_ledger.csv` and `trial_summary.json`, covering available successes and failures. New pipeline executions refresh the inventory automatically. Each run retains settings, code/data hashes, model artefacts and outputs. New LEAR fits also retain every alpha candidate's calibration score. Three candidate alphas selected on inner validation are distinguished from separate outer research experiments.

Holm-adjusted DM p-values are included over the available unique empirical test signatures, labelled **diagnostic only**. This does not repair missing trial history, unverified vintages, inspected evaluation dates, dependence assumptions or short samples. Research inference remains disabled. For a future final study, freeze the primary pinball test, its hypothesis family, dependence treatment and holdout before inspecting outcomes.

## Cost and physical sensitivity

Baseline: 1 MW / 4 MWh, 90% round-trip efficiency, empty start/end each day, throughput cost **EUR 2 per MWh charged plus discharged**, additional import fee EUR 0/MWh. A mixed-integer extension of the brief's LP prohibits simultaneous charging and discharging, including at negative prices.

The following **period-total net EUR** results change one assumption at a time. All schedules are reoptimised using unchanged price forecasts and settled at the same actual prices. Perfect foresight is recomputed using identical scenario settings.

| Scenario | Perfect foresight | LEAR | LightGBM | Naive |
|---|---:|---:|---:|---:|
| baseline | 2,502.18 | 2,210.49 | 2,065.83 | 1,976.55 |
| capacity_mwh=2 | 1,628.89 | 1,446.22 | 1,310.90 | 1,364.66 |
| capacity_mwh=8 | 2,752.01 | 2,341.84 | 2,129.83 | 1,841.97 |
| import_fee_eur_mwh=10 | 2,002.18 | 1,713.42 | 1,565.99 | 1,406.95 |
| import_fee_eur_mwh=5 | 2,246.88 | 1,959.99 | 1,837.19 | 1,691.58 |
| round_trip_efficiency=0.8 | 1,469.75 | 1,170.51 | 1,012.51 | 849.03 |
| round_trip_efficiency=0.95 | 3,047.24 | 2,740.72 | 2,788.17 | 2,586.39 |
| throughput_cost_eur_mwh=0 | 2,704.13 | 2,414.34 | 2,355.19 | 2,236.43 |
| throughput_cost_eur_mwh=10 | 1,763.57 | 1,493.36 | 1,319.85 | 1,157.32 |
| throughput_cost_eur_mwh=5 | 2,212.20 | 1,934.77 | 1,809.14 | 1,655.52 |

Battery results are simplified energy-arbitrage operating value, **not all-in commercial profit**. Market impact, capital/financing costs and unconfigured grid/tax/capacity charges are omitted. The throughput charge is a configurable wear proxy, not a calibrated degradation law. EUR/MWh costs are appropriate here; basis-point costs from equities are not mechanically applied to electricity prices that can be zero or negative. Do not choose a preferred scenario after looking at its profit.

## Data limitations

- Source period: 2025-10-08 to 2026-10-22 UTC exclusive; 9,095 complete hourly observations retained.
- Four quarter-hour solar/onshore-wind values were missing at 2025-10-25 22:00 UTC. Strict preparation stopped; the explicit historical policy excluded the incomplete hour without filling it.
- The model excludes incomplete/DST local days and affected lag-source days. This reduces the sample and can affect representativeness.
- Native 15-minute inputs are averaged to complete hours; this loses quarter-hour trading opportunities.
- Original historical forecast vintages and cutoff evidence remain unverified; external-source cross-checks and crisis-regime coverage are not established.
- Seven evaluated days do not establish calibration, stable profitability or a robust model ranking. No final untouched holdout exists.

## Run locally

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python check_quality.py --with-js  # requires Node.js on PATH; omit the flag otherwise
python serve.py
```

Keep the terminal open and visit the printed loopback address. Stop with Ctrl+C. After code updates, restart the server and hard-refresh with Ctrl+Shift+R.

```powershell
python run_pipeline.py --mode demo --evaluation-days 7
python run_pipeline.py --mode empirical --evaluation-days 7 --acknowledge-unverified-vintages
python research_audit.py
python sensitivity.py --run-id 20261024T170430888686Z_empirical_b972e4
python export_preview.py --run-id 20261024T170430888686Z_empirical_b972e4
```

New pipeline runs produce sensitivity.csv automatically; the standalone sensitivity command creates a separate supplement without editing old result archives. Existing raw downloads, historical results and API secrets are preserved. No trades are placed. The owner has deployed the exploratory backend on AWS; frontend publication is being configured.

## Code and learning map

Read ENGINEERING_GUIDE.md for architecture and naming, REQUIREMENTS_TRACEABILITY.md for scope, RESEARCH_RULES.md for the remaining evidence gates, and MODEL_SPEC.md for modelling assumptions.

- Ingestion/preparation: download_data.py, prepare_data.py, prepare_history.py.
- Information set and transforms: information_set.py, features.py, transforms.py.
- Models/evaluation: models.py and evaluation.py; LEAR-style implementation, not exact epftoolbox replication.
- Decisions/research audit: battery.py, sensitivity.py, research_audit.py, research_protocol.json.
- Orchestration/configuration: run_pipeline.py, configuration.py, config.json.
- Presentation/export: serve.py, frontend/, export_preview.py.

The agreed reduced scope has three LightGBM quantile fits within one challenger family (10/50/90%). Neural nets, nine quantiles, conformal wrappers, price simulation and multi-day storage are deferred. Research readiness is separate from passing software tests.


## Hosted portfolio preparation

Read DEPLOYMENT.md for the new FastAPI API, durable single-host queue, session-isolated experiment worker, Docker Compose and GitHub Pages build. The original local research interface still works. Hosted jobs use curated preloaded data with 1–3 evaluation days, one worker, quotas, a timeout and 24-hour retention. Run `python prepare_hosted_seed.py` before building the image. The owner has verified Docker execution locally and deployed the backend on AWS in Stockholm. Public HTTPS health checks passed at https://power-forecast-lab-api.duckdns.org/health. The GitHub Pages frontend and its cross-origin experiment flow still require publication and verification.


## Portfolio URLs

- AWS-hosted exploratory dashboard: https://power-forecast-lab-api.duckdns.org/
- Repository: https://github.com/Probeginnercodes/power-price
- Intended GitHub Pages URL (pending workflow publication): https://probeginnercodes.github.io/power-price/

To publish the frontend, choose GitHub Actions as the repository Pages source and manually run **Publish portfolio frontend**, using the HTTPS backend origin above. The workflow uploads only generated frontend assets, not local research data, environment files or private keys. Hosted research limitations remain visible; no validated trading performance is claimed.
