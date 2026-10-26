# Model and data specification

## Forecasting

A documented LEAR-style benchmark uses 24 hourly LASSOs, refit daily in a trailing 364-calendar-day window. Inputs: full price profiles at lags 1, 2 and 7 days; same-hour lag 3; target-hour load, solar and wind forecasts; calendar indicators. This is an implementation of the reduced brief, not an exact epftoolbox replication.

LASSO alpha selection uses a chronological segment inside training. LEAR intervals add training-validation residual quantiles to its point prediction; they are heuristic, not conformal guarantees. LightGBM uses three fixed-specification quantile models at 10/50/90 percent. Predeclared sorting fixes quantile crossings; raw forecasts remain saved. Every scaler and asinh fit uses its own training split.

## Evaluation

Original-scale MAE, RMSE, pinball loss, coverage, interval width and quantile calibration are reported. The DM diagnostic uses matched daily absolute errors, Newey-West/Bartlett variance and an approximate t reference with a horizon-one adjustment. Samples below 30 days are explicitly insufficient for persuasive inference. Seven-day results are development checks, not a final untouched holdout.

## Storage

The optimisation uses linear price/energy relationships with binary charging-mode variables to prohibit simultaneous charging and discharging at negative prices: a MILP extension of the basic LP. Default battery: 1 MW, 4 MWh, 90 percent round-trip efficiency, empty at both daily boundaries. Throughput cost is 2 EUR per MWh of grid-side charge plus discharge; additional import fees default to zero. Forecast schedules are frozen and settled using actual prices. Perfect foresight uses identical costs and constraints. This is simplified price-taking energy-arbitrage value, not all-in commercial profit.

## Data limitations

Historical data covers 2025-10-08 to 2026-10-22 UTC exclusive. One incomplete hour was detected at 2025-10-25 22:00 UTC: four missing quarter-hours for solar and onshore wind. Strict preparation stopped; the separate prepare_history.py policy excludes incomplete hours and records them. It produced 9095 complete hourly observations without filling values or editing originals.

Incomplete local days, 23/25-hour DST days and affected lag-source days are excluded under the initial model policy. Consequently a 364-calendar-day window contains fewer usable training days. The final DST policy needs review before external research claims.

Historical original-vintage availability remains unverified. Empirical runs are visibly exploratory and require explicit acknowledgement; the acknowledgement does not certify the evidence. Demo runs are synthetic and establish software behaviour only.

## Reproducibility and readiness

Results retain configuration, dependency versions, code/data fingerprints, model files, scalers, transforms, forecasts and battery schedules. Requirements are pinned. This is a research prototype, not a production trading service. Longer untouched evaluation, verified vintages, benchmark replication review, monitoring and deployment hardening remain necessary. No trades are placed and no server is published.

Browser preview could not reach the sandbox's loopback port. Handler tests, JavaScript syntax and end-to-end model runs were checked separately; full visual browser verification remains incomplete.
