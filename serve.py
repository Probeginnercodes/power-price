"""Local-only research dashboard. Bind to loopback; never expose to the Internet."""

import csv
import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

PROJECT = Path(__file__).resolve().parent
STATIC = PROJECT / "frontend"
STATE = {"running": False, "status": "idle", "log_file": None, "exit_code": None}
LOCK = threading.Lock()
PORT = 8765


def jobs():
    """List recent run manifests; incomplete/corrupt manifests are skipped."""
    entries = []
    for path in sorted((PROJECT / "data" / "results").glob("*/run.json"), reverse=True):
        try:
            run_manifest = json.loads(path.read_text(encoding="utf-8"))
            entries.append(
                {
                    "id": path.parent.name,
                    "mode": run_manifest.get("mode"),
                    "status": run_manifest.get("status"),
                }
            )
        except (OSError, ValueError):
            pass
    return entries[:30]


def launch(options):
    """Validate dashboard options and start at most one background subprocess."""
    if not isinstance(options, dict):
        raise ValueError("Run settings must be a JSON object")
    mode = options.get("mode", "demo")
    evaluation_days = int(options.get("days", 7))
    training_days = int(options.get("training_days", 364))
    if (
        mode not in ("demo", "empirical")
        or not 1 <= evaluation_days <= 30
        or not 60 <= training_days <= 730
    ):
        raise ValueError("Invalid run settings")
    if mode == "empirical" and options.get("acknowledge") is not True:
        raise ValueError("Acknowledge unverified historical vintages first")
    with LOCK:
        if STATE["running"]:
            raise ValueError("A run is already active")
        log_directory = PROJECT / "data" / "frontend_logs"
        log_directory.mkdir(parents=True, exist_ok=True)
        log_path = log_directory / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".log"
        )
        STATE.update(running=True, status="running", log_file=str(log_path), exit_code=None)
    command = [
        sys.executable,
        str(PROJECT / "run_pipeline.py"),
        "--mode",
        mode,
        "--evaluation-days",
        str(evaluation_days),
        "--training-days",
        str(training_days),
    ]
    if mode == "empirical":
        command.append("--acknowledge-unverified-vintages")

    def worker():
        exit_code = 1
        try:
            with log_path.open("w", encoding="utf-8") as file:
                exit_code = subprocess.run(
                    command, cwd=PROJECT, stdout=file, stderr=subprocess.STDOUT
                ).returncode
        except Exception as error:
            log_path.write_text(str(error), encoding="utf-8")
        finally:
            with LOCK:
                STATE.update(
                    running=False,
                    status="success" if exit_code == 0 else "failed",
                    exit_code=exit_code,
                )

    threading.Thread(target=worker, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    """Serve allowlisted local assets and experiment artefacts, never arbitrary paths."""

    def log_message(self, *args):
        pass

    def reply(self, status, body, content_type="application/json"):
        """Send a bounded API/static response with caching disabled."""
        payload = (
            json.dumps(body, allow_nan=False).encode()
            if content_type == "application/json"
            else body
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        try:
            parsed = urlsplit(self.path)
            path = parsed.path
            if path == "/api/status":
                with LOCK:
                    state = dict(STATE)
                log_path = (
                    Path(state["log_file"]).read_text(encoding="utf-8")[-12000:]
                    if state.get("log_file") and Path(state["log_file"]).is_file()
                    else ""
                )
                state.pop("log_file", None)
                datasets = []
                for report in (PROJECT / "data" / "processed").glob("*/validation.json"):
                    data = json.loads(report.read_text(encoding="utf-8"))
                    datasets.append(
                        {
                            "id": report.parent.name,
                            "hours": data.get("hourly_rows"),
                            "start": data.get("start_utc"),
                            "end": data.get("end_utc_exclusive"),
                        }
                    )
                self.reply(
                    200,
                    {
                        "job": state,
                        "log": log_path,
                        "runs": jobs(),
                        "research": json.loads(
                            (PROJECT / "data" / "research" / "trial_summary.json").read_text(
                                encoding="utf-8"
                            )
                        )
                        if (PROJECT / "data" / "research" / "trial_summary.json").is_file()
                        else None,
                        "datasets": sorted(
                            datasets, key=lambda dataset: dataset["hours"] or 0, reverse=True
                        ),
                    },
                )
                return
            if path == "/api/research/download":
                artifact_name = parse_qs(parsed.query).get("file", [""])[0]
                if artifact_name not in ("trial_ledger.csv", "trial_summary.json"):
                    raise ValueError("Invalid research artefact")
                self.reply(
                    200,
                    (PROJECT / "data" / "research" / artifact_name).read_bytes(),
                    "application/octet-stream",
                )
                return
            if path.startswith("/api/result/"):
                run_id = path.split("/")[-1]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
                    raise ValueError("Invalid run id")
                folder = PROJECT / "data" / "results" / run_id
                report = json.loads((folder / "results.json").read_text(encoding="utf-8"))
                result = {"report": report}
                sensitivity_path = folder / "sensitivity.csv"
                if sensitivity_path.is_file():
                    with sensitivity_path.open(encoding="utf-8", newline="") as sensitivity_file:
                        result["sensitivity"] = list(csv.DictReader(sensitivity_file))
                else:
                    # Derived supplements never modify the archived original experiment.
                    supplements = sorted(
                        (PROJECT / "data" / "sensitivity").glob(run_id + "_*/sensitivity.csv"),
                        key=lambda candidate: candidate.stat().st_mtime,
                    )
                    if supplements:
                        with supplements[-1].open(encoding="utf-8", newline="") as sensitivity_file:
                            result["sensitivity"] = list(csv.DictReader(sensitivity_file))
                for artifact_name in [
                    "forecasts",
                    "battery_values",
                    "battery_dispatch",
                    "metrics_by_hour",
                ]:
                    with (folder / f"{artifact_name}.csv").open(
                        encoding="utf-8", newline=""
                    ) as file:
                        result[artifact_name] = list(csv.DictReader(file))
                self.reply(200, result)
                return
            if path == "/api/download":
                query = parse_qs(parsed.query)
                run_id = query.get("run", [""])[0]
                artifact_name = query.get("file", [""])[0]
                if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id) or artifact_name not in [
                    "forecasts.csv",
                    "metrics.csv",
                    "battery_values.csv",
                    "battery_dispatch.csv",
                    "results.json",
                    "battery_summary.csv",
                    "sensitivity.csv",
                ]:
                    raise ValueError("Invalid artifact")
                artifact_path = PROJECT / "data" / "results" / run_id / artifact_name
                if artifact_name == "sensitivity.csv" and not artifact_path.is_file():
                    supplements = sorted(
                        (PROJECT / "data" / "sensitivity").glob(run_id + "_*/sensitivity.csv"),
                        key=lambda candidate: candidate.stat().st_mtime,
                    )
                    if supplements:
                        artifact_path = supplements[-1]
                content = artifact_path.read_bytes()
                self.reply(
                    200,
                    content,
                    "text/csv; charset=utf-8"
                    if artifact_name.endswith(".csv")
                    else "application/octet-stream",
                )
                return
            allowed = {
                "/": "index.html",
                "/app.js": "app.js",
                "/config.js": "config.js",
                "/api_client.js": "api_client.js",
                "/ui_helpers.js": "ui_helpers.js",
                "/style.css": "style.css",
            }
            if path not in allowed:
                self.reply(404, {"error": "Not found"})
                return
            file = STATIC / allowed[path]
            content_type = (
                "text/html; charset=utf-8"
                if file.suffix == ".html"
                else "text/css; charset=utf-8"
                if file.suffix == ".css"
                else "application/javascript; charset=utf-8"
            )
            self.reply(200, file.read_bytes(), content_type)
        except FileNotFoundError:
            self.reply(404, {"error": "Result not available yet"})
        except Exception as error:
            self.reply(400, {"error": str(error)})

    def do_POST(self):
        # Browser origins must be this local application. No credentials accepted.
        origin = self.headers.get("Origin")
        if origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            self.reply(403, {"error": "Local same-origin requests only"})
            return
        if self.path != "/api/run":
            self.reply(404, {"error": "Not found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 < content_length < 4096:
                raise ValueError("Invalid request size")
            options = json.loads(self.rfile.read(content_length))
            launch(options)
            self.reply(202, {"status": "started"})
        except Exception as error:
            self.reply(400, {"error": str(error)})


if __name__ == "__main__":
    print(f"Power Forecast Lab: http://127.0.0.1:{PORT}", flush=True)
    print("Local testing only. Stop with Ctrl+C. Keep your API token in .env.", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
