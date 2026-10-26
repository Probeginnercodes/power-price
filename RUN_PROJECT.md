# Running the reduced project

Activate the project virtual environment, then run:

```powershell
python -m pip install -r requirements.txt
python -m unittest -v
python serve.py
```

Open the local address printed by the server in your browser.

For the terminal workflow:

```powershell
python run_pipeline.py --mode demo --evaluation-days 7
python run_pipeline.py --mode empirical --evaluation-days 7 --acknowledge-unverified-vintages
```

Demo results use synthetic data. Historical results are exploratory because original forecast publication/vintage evidence remains unverified.

Results and fitted models are stored in data/results. Configurable model and battery settings are in config.json. See MODEL_SPEC.md for assumptions and limits.


## Research rules and sensitivity

```powershell
python research_audit.py
python sensitivity.py --run-id 20261024T170430888686Z_empirical_b972e4
python run_pipeline.py --mode empirical --acknowledge-unverified-vintages --require-verified-vintages
```

The last command intentionally stops because historical original-vintage evidence is unverified. It is an evidence gate, not a broken model. Ordinary acknowledged historical runs remain exploratory. New runs generate cost/physical sensitivity and refresh the trial ledger; the standalone sensitivity command leaves old archives unchanged. Read README.md for negative results, the leakage checklist and the measured scenario table. Restart serve.py and hard-refresh to load the Corporate Blues dashboard and research export routes.
