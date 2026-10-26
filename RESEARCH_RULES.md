# Research rules and remaining evidence gates

The README now contains the question, success test, negative result table, feature/split/normalisation checklist, trial inventory and measured cost sensitivities. This fixes their missing presentation; it does not alter the chronology of research already done.

## What cannot be repaired retrospectively

1. The question/success test were not consolidated into the README before data inspection. We disclose that fact rather than backdate them.
2. Original historical load/wind/solar forecast vintages and exact decision-time availability are not proved by current downloads. A strict verified-vintage command fails closed. Acknowledgement permits exploration only.
3. Available run manifests do not establish the lifetime number of human experiments. The ledger reports archived evidence and labels pre-archive trials unknown.
4. The seven-day development period has been inspected. A future final holdout must be assigned, frozen and kept untouched; it is not created merely by writing a protocol today.
5. Holm adjustment over available archived tests is a diagnostic, not a correction for an unknown complete trial history or a remedy for leakage. Current DM compares absolute error; the primary probabilistic success objective remains pinball loss.

## Publication evidence acceptance workflow

For every forecast input and lagged auction-price value, retain the original source document/revision, publication timestamp, delivery interval, request type, unit, file hash and a reproducible link to the exact value used. Verify that this exact revision was available strictly before the verified market cutoff. An XML document's creation time or today's download time is not sufficient by itself. Backfilled/revised forecasts cannot be treated as original vintages without supporting evidence.

When evidence is unavailable, either obtain a documented point-in-time archive or collect snapshots prospectively before the declared cutoff. Existing historical results remain exploratory. The strict pipeline option deliberately has no user-supplied boolean bypass for this evidence gap. Implementing a verified pathway requires actual row-level evidence, independent review and tests; it is not enabled in the current code.

## Trial policy

Refresh `python research_audit.py` after adding legacy runs; new pipeline attempts refresh automatically on completion/failure. Preserve failed runs and candidate scores. Record human changes and their motivations in RESEARCH_DECISIONS.md before running them. Mechanical refactors, repeated runs, inner validation searches, changed outer model settings and newly inspected test periods are distinct categories. Do not declare unknown earlier trial counts to be zero.

## Cost policy

The ten-scenario one-factor-at-a-time grid is declared in sensitivity.py. Reoptimise every schedule and the perfect-foresight comparison under each cost/physical setting. Use the same forecasts and settlement prices. Baseline includes efficiency and throughput charges; omitted commercial charges remain explicitly named. The sensitivity grid is not an opportunity to select the best-looking profit after observing outcomes.

## Final-study gate

Before claiming success: verify original-vintage inputs and auction timing; assign a future/uninspected evaluation period; freeze settings, metric priorities, calibration target and hypothesis family; record all subsequent trials; report both positive and negative results with sampling limitations. Current research_protocol.json is a retrospective development declaration, not preregistration of the completed experiment.
