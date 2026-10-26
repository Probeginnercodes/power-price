# Engineering guide

This is the reduced Project 5 research application. The refactor improves maintainability; it does not establish that the historical forecasts are calibrated or that the application is ready for a trading desk.

## Responsibilities and data flow

| Layer | Files | Responsibility |
|---|---|---|
| Ingestion | download_data.py | Request ENTSO-E data, preserve raw responses and token-redacted metadata |
| Validation | prepare_data.py, prepare_history.py | Enforce units, UTC grids and complete-hour policy; record exclusions |
| Information set | information_set.py | Document assumed cutoff and audit publication evidence |
| Feature engineering | features.py, models.design_table | Educational lineage table and production-path daily profile matrix respectively |
| Transform | transforms.py | Fit robust asinh parameters only within the training split |
| Models | models.py | Separate design construction, alpha selection, hourly LEAR fits and quantile fits |
| Evaluation | evaluation.py | Point/probabilistic scores, calibration and matched daily DM diagnostics |
| Decisions | battery.py | Optimise planning schedules and settle separately at actual prices |
| Configuration | configuration.py, config.json | Validate effective run settings before creating a result directory |
| Orchestration | run_pipeline.py | Select history, roll daily fits, checkpoint tables and record run outcomes |
| Presentation | serve.py, frontend/ | Loopback API and dashboard over saved research artefacts |
| Export | export_preview.py | Embed results/assets in a read-only HTML snapshot |

The two feature builders have different purposes. `features.py` is an educational same-hour lag/lineage export. The modelling path uses `models.design_table`, including full prior-day profiles. Do not assume their feature columns are interchangeable. Neither builder proves publication availability.

## Conventions

- Python functions and variables use snake_case; classes use PascalCase; module constants use UPPER_SNAKE_CASE. Frontend JavaScript uses camelCase.
- Include units in physical quantities: charge_mw, capacity_mwh, total_net_revenue. Use names such as calibration_residuals instead of a, b or tr for modelling roles.
- Retain existing public function arguments and CSV/JSON keys when compatibility matters. Mathematical quantile parameters y/q/tau remain at the public scoring boundary; their meaning is documented.
- Functions should have one main responsibility. Private model helpers start with an underscore. Public numerical interfaces include type hints and docstrings; type checking is not currently a mandatory gate.
- Comments explain assumptions, chronology, units and numerical constraints. Do not comment every obvious assignment.
- Errors at numerical boundaries fail clearly. Exception chaining preserves causes. Broad exception handling is reserved for run manifests and HTTP boundaries that must report failures.
- Keep scientific model changes separate from refactors. Freeze baselines before tuning and record every experiment's settings and provenance.

## Quality checks

From an activated Python environment:

```powershell
python -m pip install -r requirements-dev.txt
python check_quality.py
```

With Node.js installed and on PATH:

```powershell
python check_quality.py --with-js
npm install --ignore-scripts
npm run format:check
```

Apply mechanical formatting with `python -m ruff format .` and `npm run format`. Ruff checks imports and selected correctness/style rules; Prettier handles JS/HTML/CSS formatting. These tools complement scientific tests; they do not establish model validity. `.editorconfig` supplies consistent editor defaults. The included GitHub Actions workflow runs these checks when this source is put in a GitHub repository.

## Compatibility and intentional changes

- Existing top-level commands remain valid; a new package hierarchy is not required to use this refactor.
- Existing result directories and raw downloads are not migrated or edited.
- Existing forecast, calibration and battery output schemas remain compatible.
- `metrics_by_hour.csv` gains `rmse`, required by the brief alongside hourly MAE.
- Unsupported quantile sets, unknown configuration keys, nonfinite physical settings and invalid run identifiers fail early.
- A historical-day comparison against preserved original source established identical forecasts and diagnostics, battery equality within EUR 1e-8, and overall score equality within 1e-12. This is a regression check on one day, not a proof for every dataset.

## Operational limits

The local HTTP server and in-memory job state are appropriate for a research workstation. They are not durable job scheduling, authenticated multi-user access or production deployment infrastructure. Original forecast vintages remain unverified; chronological train/test splitting does not resolve this. The current evaluation period was already inspected and is not an untouched final holdout. Adding infrastructure does not repair these research limitations.

For learning, follow a single row from raw XML to hourly CSV, design matrix, transformed target, forecast, loss and settled battery revenue. Read each function's contract before its implementation, then modify a small example and predict the test outcome before running it.

## Research-rule controls and dashboard update

The README is the consolidated results/leakage/cost document. research_protocol.json records the retrospective protocol and unresolved holdout. research_audit.py inventories successful/failed archived runs, deduplicates exact test signatures and adds diagnostic Holm adjustment without claiming unknown earlier trials are absent. RESEARCH_DECISIONS.md is the human hypothesis log. sensitivity.py declares ten one-factor scenarios and reoptimises matched battery policies; new runs produce sensitivity.csv automatically. Existing runs receive separate supplements.

Use --require-verified-vintages with an empirical run to enforce the unavailable-evidence gate. This intentionally fails rather than accepting an assertion as proof. Normal acknowledged empirical runs remain exploratory.

The dashboard uses Corporate Blues (#003366, #00509e, #007acc, #66a3ff, #cce0ff), raised card/bar shadows, an isometric decorative battery and SVG depth effects. Quantitative coordinates, units and chart scales are not tilted. Offline system-font fallbacks avoid requiring a remote font service. Browser visual QA was not repeated because the earlier browser policy prohibited the local preview; Node rendering contracts and parser/format checks cover the presentation paths without claiming full browser verification.
