# Reduced-project requirement traceability

The uploaded full brief is broader than the explicitly agreed reduced project. This table tracks that reduced scope rather than claiming all full-project tasks are complete.

| Requirement | Implementation / checks | Status and limits |
|---|---|---|
| DE-LU prices and day-ahead load/wind/solar | download_data.py; raw XML/metadata; downloader tests | Implemented; source availability governs history |
| UTC alignment and native resolution | prepare_data.py, prepare_history.py; preparation tests | Implemented; complete hours only; hourly averaging loses quarter-hour opportunities |
| Explicit DST handling | preparation, feature and lag tests | UTC identity preserved; modelling deliberately excludes incomplete/23/25-hour local target and lag-source days |
| Information-set table and timestamps | information_set.py; availability tests | Table/checks implemented; historical forecast-vintage evidence remains UNVERIFIED |
| Train-only asinh and inverse evaluation | transforms.py; transform and leakage tests | Implemented; inverse point estimate is not asserted to equal conditional mean |
| LEAR with 1/2/3/7-day lags and exogenous inputs | models.py; saved hourly coefficients and transforms | LEAR-style 24 hourly LASSOs, daily refits, 364 calendar days by default; not exact epftoolbox replication |
| LightGBM quantile challenger | models._fit_quantile_models | One model family with separate 10/50/90% fits in reduced scope; raw crossings retained and sorting declared |
| Naive forecast | models.forecast_day | Same local hour yesterday |
| Pinball and coverage | evaluation.py; frontend calibration table; scoring tests | Implemented; existing historical results fail nominal coverage targets |
| Overall/by-hour MAE and RMSE | evaluation.evaluate | Implemented; hourly RMSE added in refactor |
| Diebold-Mariano comparison | evaluation.dm_test | Matched daily absolute losses, HAC variance; short samples diagnostic; eligibility is not a significance guarantee |
| Battery PF / model / naive value | battery.py; physical feasibility and value-bound tests | Implemented with equal settings and actual-price settlement; binary modes extend LP to MILP |
| README results/leakage/cost rules | README.md, RESEARCH_RULES.md, research_protocol.json | Consolidated retrospectively; cannot claim day-one timing |
| Trial accounting | research_audit.py; RESEARCH_DECISIONS.md | Archive inventory and diagnostic Holm adjustment implemented; lifetime human trial count unknown |
| Cost/physical sensitivity | sensitivity.py; sensitivity.csv; dashboard | Ten declared one-factor scenarios with matched reoptimisation; omitted commercial costs explicit |
| Reproducibility and reporting | run_pipeline.py; config/dependency/source hashes; dashboard/exports | Local research workflow; no untouched final holdout established |

## Deferred full-brief extensions

Weekly naive; nine quantiles; neural networks; quantile regression averaging; conformal adjustment; PIT/coverage hypothesis testing; external-source cross-checks; gas/carbon features; crisis-regime evaluation; price simulation; multi-day flexibility and wider multi-factor battery sensitivity studies beyond the implemented ten-scenario grid are not part of this reduced implementation. They should not be marked complete in a submission.

## Research success remains separate from software completion

The mentor's success test requires calibrated quantile forecasts outperforming the linear benchmark on pinball loss and an honest battery comparison. The current seven-day historical results do not establish that success. Resolve input vintage evidence, investigate calibration/underprediction, and predeclare a longer evaluation protocol before making empirical claims. Code cleanup deliberately does not tune models to the already inspected week.
