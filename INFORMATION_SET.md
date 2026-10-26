# Information-set audit

Run `python information_set.py` after preparation; run `python -m unittest -v` for the combined tests.

Outputs: feature_definitions.csv, availability_audit.csv, delivery_day_cutoffs.csv and report.json under data/information_set/<timestamp>/.

The initial cutoff is D-1 at 11:00 Europe/Berlin. This is a research assumption, not a verified market deadline. Change it with --cutoff-local HH:MM after reviewing market rules. UTC conversion respects daylight saving.

Current forecasts have no verified original publication/vintage linkage. Therefore the report deliberately marks them unverified and the command returns a nonzero training-gate exit status, even though the audit files were written successfully. This is not evidence of a broken download. Received and document creation timestamps are clues, not proof that the exact values were available at the historical forecast cutoff.

The seven-UTC-day sample has six complete local delivery days and two partial boundary days. Use complete local days for daily forecasting and battery evaluation. Target-day prices are labels only; local calendar values are known in advance. Price lags are planned, not constructed in this file.

All 19 tests passed after adding the seven publication-time checks. No original download or processed table is modified by the audit.
