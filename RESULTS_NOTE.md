# Development results — exploratory, unverified forecast vintages

This note describes a seven-day software/research check, not a final untouched evaluation or a trading recommendation.

Data: DE-LU; 2025-10-08 to 2026-10-22 UTC exclusive. The complete-hour policy retained 9095 hourly observations and excluded one incomplete hour. Forecast delivery dates: 2026-10-15, 2026-10-16, 2026-10-17, 2026-10-18, 2026-10-19, 2026-10-20, 2026-10-21.

## Forecast results

| Model | MAE EUR/MWh | Mean pinball | 80% coverage |
|---|---:|---:|---:|
| lear | 39.97 | 8.72 | 67.3% |
| lightgbm | 30.48 | 11.74 | 44.0% |
| naive | 27.30 | — | — |

LightGBM has lower point MAE than LEAR in this sample, but worse pinball loss and substantial undercoverage. The naive point forecast has the lowest MAE. The project success criterion of calibrated quantiles beating the benchmark has NOT been established. Do not tune on these seven days and call them a final holdout.

The DM p-value is diagnostic only: there are seven matched daily losses and the report marks inference as ineligible. Forecast-vintage availability remains unresolved.

## Battery results

| Policy | Net value EUR | Share of upper bound |
|---|---:|---:|---:|
| lear | 2210.49 | 88.3% |
| lightgbm | 2065.83 | 82.6% |
| naive | 1976.55 | 79.0% |
| perfect_foresight | 2502.18 | 100.0% |

Values are for the configured 1 MW/4 MWh daily battery, with 90% round-trip efficiency, empty initial/terminal charge, throughput costs and zero extra import fee. Forecast schedules are settled at actual prices. No simultaneous charging/discharging is allowed. These are simplified price-taking energy-arbitrage values, not commercial profit forecasts.

## Limits and next research work

Verify exact forecast vintages/publication timing, establish a longer untouched test period, review benchmark replication and DST policy, and assess interval calibration without test-set tuning. Production security, monitoring and deployment hardening are out of scope for this local test application.

Software verification: 64 automated tests passed, JavaScript syntax passed, and seven-day synthetic and exploratory empirical end-to-end runs completed. The browser sandbox could not reach localhost and rejected local-file previews, so no full visual browser verification is claimed.
