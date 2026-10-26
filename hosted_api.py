"""Hosted FastAPI service: no model training in HTTP request handlers."""

import csv
import json
import re
import time
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from hosted_settings import PROJECT, HostedSettings
from hosted_store import JobStore, QueueLimitError

ARTIFACTS = {
    "forecasts.csv",
    "metrics.csv",
    "calibration.csv",
    "metrics_by_hour.csv",
    "battery_values.csv",
    "battery_dispatch.csv",
    "battery_summary.csv",
    "sensitivity.csv",
    "results.json",
}


class RunOptions(BaseModel):
    """Public visitors can select bounded settings, never commands or file paths."""

    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["demo", "empirical"] = "demo"
    days: Annotated[int, Field(ge=1, le=3)] = 1
    training_days: Literal[90, 364] = 364
    acknowledge: bool = False


def public_report(report: dict) -> dict:
    """Drop filesystem provenance paths while retaining hashes and research warnings."""
    result = dict(report)
    source = str(result.get("source_file", "")).replace("\\", "/")
    result["source_file"] = "/".join(source.split("/")[-2:])
    return result


def create_app(settings: HostedSettings | None = None) -> FastAPI:
    settings = settings or HostedSettings.from_environment()
    store = JobStore(settings)
    app = FastAPI(title="Power Forecast Lab demo", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def bounded_requests(request: Request, call_next):
        if request.method == "POST":
            if request.headers.get("origin") not in settings.origins:
                return JSONResponse({"error": "Request origin is not allowed"}, status_code=403)
            length = request.headers.get("content-length", "0")
            if not length.isdigit() or not 0 < int(length) <= 2048:
                return JSONResponse(
                    {"error": "Request must include a body of at most 2048 bytes"}, status_code=413
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_options(request, error):
        return JSONResponse(
            {
                "error": "Use 1–3 evaluation days, 90 or 364 training days, and a supported mode. Unknown settings are rejected."
            },
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"error": error.detail}, status_code=error.status_code)

    def owner(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Start a demo session first")
        identity = store.owner(authorization[7:])
        if not identity:
            raise HTTPException(401, "Session expired; reload the page")
        return identity

    def folder_for(run_id: str, identity: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise HTTPException(404, "Result not found")
        if (
            run_id == "featured_historical"
            and (settings.seed_directory / "featured" / "results.json").is_file()
        ):
            return settings.seed_directory / "featured"
        job = store.result_job(identity, run_id)
        if not job:
            raise HTTPException(404, "Result not found or expired")
        return settings.root / "jobs" / job["id"] / "data" / "results" / run_id

    @app.get("/health")
    def health():
        heartbeat = store.pulse()
        return {
            "status": "ok",
            "worker_ready": heartbeat is not None
            and time.time() - heartbeat < settings.timeout_seconds + 45,
        }

    @app.post("/api/session")
    def session(request: Request):
        try:
            token = store.session(request.client.host)
        except QueueLimitError as error:
            raise HTTPException(429, str(error)) from error
        return {"token": token, "expires_in_seconds": 7 * 86400}

    @app.post("/api/run", status_code=202)
    def submit(
        options: RunOptions, request: Request, authorization: str | None = Header(default=None)
    ):
        identity = owner(authorization)
        if options.mode == "empirical" and not options.acknowledge:
            raise HTTPException(
                400,
                "Historical inputs have unverified vintages; acknowledge exploratory mode first",
            )
        if (
            options.mode == "empirical"
            and not (settings.seed_directory / "historical" / "hourly.csv").is_file()
        ):
            raise HTTPException(503, "Historical seed data is not installed")
        heartbeat = store.pulse()
        if heartbeat is None or time.time() - heartbeat > settings.timeout_seconds + 45:
            raise HTTPException(503, "Experiment worker is not ready. Please retry shortly.")
        try:
            job_id = store.submit(identity, request.client.host, options.model_dump())
        except QueueLimitError as error:
            raise HTTPException(429, str(error)) from error
        return {"status": "queued", "job_id": job_id}

    @app.get("/api/status")
    def status(authorization: str | None = Header(default=None)):
        jobs = store.list_jobs(owner(authorization))
        active = next((job for job in jobs if job["status"] in ("running", "queued")), None)
        latest = active or (jobs[0] if jobs else None)
        job_state = {
            "running": active is not None,
            "status": latest["status"] if latest else "idle",
            "job_id": latest["id"] if latest else None,
        }
        runs = [
            {
                "id": job["result_id"],
                "status": "success",
                "mode": json.loads(job["options"])["mode"],
            }
            for job in jobs
            if job["status"] == "success"
        ]
        if (settings.seed_directory / "featured" / "results.json").is_file():
            runs.append({"id": "featured_historical", "status": "success", "mode": "empirical"})
        log = "One worker processes the durable queue. Results expire after 24 hours; download them before then."
        if latest and latest["error"]:
            log += "\n" + latest["error"]
        datasets = []
        validation_path = settings.seed_directory / "historical" / "validation.json"
        if validation_path.is_file():
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            datasets.append(
                {
                    "id": "hosted_history",
                    "hours": validation.get("hourly_rows"),
                    "start": validation.get("start_utc"),
                    "end": validation.get("end_utc_exclusive"),
                }
            )
        return {"job": job_state, "log": log, "runs": runs, "datasets": datasets, "research": None}

    @app.get("/api/result/{run_id}")
    def result(run_id: str, authorization: str | None = Header(default=None)):
        folder = folder_for(run_id, owner(authorization))
        if not (folder / "results.json").is_file():
            raise HTTPException(404, "Result is not available")
        response = {
            "report": public_report(
                json.loads((folder / "results.json").read_text(encoding="utf-8"))
            )
        }
        for name in (
            "forecasts",
            "battery_values",
            "battery_dispatch",
            "metrics_by_hour",
            "sensitivity",
        ):
            path = folder / f"{name}.csv"
            if path.is_file():
                with path.open(encoding="utf-8", newline="") as file:
                    response[name] = list(csv.DictReader(file))
        return response

    @app.get("/api/download")
    def download(run: str, file: str, authorization: str | None = Header(default=None)):
        if file not in ARTIFACTS:
            raise HTTPException(404, "Unknown artefact")
        folder = folder_for(run, owner(authorization))
        if not (folder / file).is_file():
            raise HTTPException(404, "Artefact not available")
        if file == "results.json":
            content = public_report(json.loads((folder / file).read_text(encoding="utf-8")))
            return Response(
                json.dumps(content),
                media_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="results.json"'},
            )
        return FileResponse(folder / file, filename=file, media_type="text/csv")

    @app.get("/config.js")
    def configuration():
        return Response(
            'window.FORECAST_CONFIG = {hosted: true, apiBase: ""};',
            media_type="application/javascript",
        )

    @app.get("/{asset:path}")
    def static_asset(asset: str):
        allowed = {
            "": "index.html",
            "index.html": "index.html",
            "style.css": "style.css",
            "app.js": "app.js",
            "ui_helpers.js": "ui_helpers.js",
            "api_client.js": "api_client.js",
        }
        if asset not in allowed:
            raise HTTPException(404, "Not found")
        return FileResponse(PROJECT / "frontend" / allowed[asset])

    return app
