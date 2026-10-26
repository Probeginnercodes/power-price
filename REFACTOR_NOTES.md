# Code-quality refactor

## Changes

- Reformatted all Python sources/tests with Ruff, organised imports and removed unused imports.
- Expanded compressed JS/HTML/CSS with pinned Prettier formatting.
- Split model fitting into design, LEAR, quantile and daily-forecast responsibilities.
- Split rolling forecasts and CSV persistence out of run orchestration.
- Replaced ambiguous model and battery variables with names describing their roles and units.
- Added mathematical comments and function contracts for ingestion, time alignment, transformation, feature construction, fitting, scoring and dispatch.
- Added typed battery schedules, annotated numerical interfaces, named solver/tolerance constants and configuration validation.
- Added hourly RMSE, input-shape/nonfinite checks, explicit run-identifier validation and preview-embedding regression coverage.
- Added repeatable quality commands, editor settings, development dependencies and a CI workflow.
- Preserved raw data and existing outputs. Existing top-level commands and dashboard interfaces remain compatible.

## Verification

See refactor_verification.json for the historical-day comparison. Forecasts and daily diagnostics matched the preserved original implementation exactly. Battery outputs and overall metrics matched within their declared numerical tolerances. A complete one-day synthetic CLI run also completed successfully. Final local gates passed: 80 Python tests, 10 JavaScript helper checks, JavaScript syntax, Ruff lint/format and Prettier formatting. Browser visual interactions were not revalidated in this refactor.

## Remaining work

This is improved research software, not a production trading service. Historical vintage proof, final holdout design, longer evaluation and calibration remain research tasks. Typed settings are validated at runtime; a comprehensive static type-checking rollout, durable scheduling, authentication and deployment monitoring are not included.
