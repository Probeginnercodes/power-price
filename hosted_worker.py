"""Single model worker with durable claims, subprocess timeout and result retention."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from hosted_settings import PROJECT, HostedSettings
from hosted_store import JobStore


def job_directory(settings: HostedSettings, job_id: str) -> Path:
    """Only worker-owned UUID directories may be created or removed."""
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("Invalid job identifier")
    root = (settings.root / "jobs").resolve()
    directory = (root / job_id).resolve()
    if directory.parent != root:
        raise ValueError("Job directory escapes worker root")
    return directory


def execute_job(store: JobStore, job: dict) -> None:
    settings = store.settings
    directory = job_directory(settings, job["id"])
    directory.mkdir(parents=True, exist_ok=True)
    options = json.loads(job["options"])
    command = [
        sys.executable,
        str(PROJECT / "run_pipeline.py"),
        "--mode",
        options["mode"],
        "--evaluation-days",
        str(options["days"]),
        "--training-days",
        str(options["training_days"]),
    ]
    if options["mode"] == "empirical":
        historical = directory / "data" / "processed" / "hosted_history"
        historical.mkdir(parents=True, exist_ok=True)
        for name in ("hourly.csv", "validation.json"):
            shutil.copy2(settings.seed_directory / "historical" / name, historical / name)
        command.extend(["--processed-id", "hosted_history", "--acknowledge-unverified-vintages"])
    environment = dict(
        os.environ,
        POWER_DATA_DIR=str(directory / "data"),
        PYTHONUNBUFFERED="1",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    # Public jobs use preloaded data; ENTSO-E credentials never enter the worker.
    environment.pop("ENTSOE_API_TOKEN", None)
    environment.pop("ENTSOE_TOKEN", None)
    try:
        with (directory / "worker.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command,
                cwd=PROJECT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=settings.timeout_seconds,
                check=False,
            )
        reports = list((directory / "data" / "results").glob("*/results.json"))
        if completed.returncode != 0 or len(reports) != 1:
            store.finish(
                job["id"],
                "failed",
                error="Experiment failed. Choose a smaller supported experiment or retry later.",
            )
        else:
            store.finish(job["id"], "success", result_id=reports[0].parent.name)
    except subprocess.TimeoutExpired:
        store.finish(
            job["id"],
            "timed_out",
            error="Experiment exceeded the demo time limit. Try one evaluation day.",
        )
    except Exception:
        store.finish(job["id"], "failed", error="Worker could not complete this experiment.")
        raise


def run_once(store: JobStore) -> bool:
    """Process at most one claim; SQLite prevents concurrent worker execution."""
    for job_id in store.expired():
        directory = job_directory(store.settings, job_id)
        if directory.exists():
            shutil.rmtree(directory)
    job = store.claim()
    if job is None:
        return False
    try:
        execute_job(store, job)
    except Exception:
        store.finish(job["id"], "failed", error="Worker could not initialise this experiment.")
        raise
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    job_store = JobStore(HostedSettings.from_environment())
    while True:
        try:
            processed = run_once(job_store)
        except Exception as error:
            print(f"Worker error: {type(error).__name__}", flush=True)
            processed = False
        if args.once:
            break
        if not processed:
            time.sleep(2)
