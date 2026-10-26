"""Download DE-LU prices/forecasts; preserve raw XML and native-resolution CSVs.

Example: python download_data.py --start 2026-10-15 --end 2026-10-22
Dates are UTC; end is exclusive. Never print a request URL or API token.
"""

import argparse
import hashlib
import json
import logging
import math
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pandas as pd
import requests
from dotenv import load_dotenv
from entsoe import EntsoePandasClient

PROJECT = Path(__file__).resolve().parent


def save_json(path, value):
    """Create a new JSON artefact; exclusive mode prevents overwriting an archive."""
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, indent=2)


def archive_response(directory):
    """A requests hook runs before entsoe-py parses or rejects each response."""

    def archive(response, *args, **kwargs):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        stem = f"{stamp}_{uuid.uuid4().hex}"
        body = response.content
        with (directory / f"{stem}.xml").open("xb") as file:
            file.write(body)
        # Do not store the full URL, request headers, cookies or token.
        params = {
            key: value
            for key, value in parse_qsl(urlsplit(response.request.url).query)
            if key.lower() != "securitytoken"
        }
        metadata = {
            "received_utc": datetime.now(timezone.utc).isoformat(),
            "request_parameters_without_token": params,
            "http_status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "sha256": hashlib.sha256(body).hexdigest(),
            "body_file": f"{stem}.xml",
        }
        try:
            root = ET.fromstring(body)
            metadata["document_created_utc"] = root.findtext("{*}createdDateTime")
            metadata["document_revision"] = root.findtext("{*}revisionNumber")
            metadata["resolutions"] = sorted(
                {e.text for e in root.findall(".//{*}resolution") if e.text}
            )
            metadata["currency_units"] = sorted(
                {e.text for e in root.findall(".//{*}currency_Unit.name") if e.text}
            )
            metadata["measure_units"] = sorted(
                {
                    e.text
                    for e in root.findall(".//{*}price_Measure_Unit.name")
                    + root.findall(".//{*}quantity_Measure_Unit.name")
                    if e.text
                }
            )
        except ET.ParseError:
            metadata["xml_parseable"] = False
        save_json(directory / f"{stem}.metadata.json", metadata)
        return response

    return archive


def clean_result(result, start, end):
    """Normalise parsed API output to sorted UTC rows within the exclusive request interval."""
    if isinstance(result, pd.Series):
        result = result.rename("price_eur_mwh").to_frame()
    if not isinstance(result, pd.DataFrame) or not isinstance(result.index, pd.DatetimeIndex):
        raise ValueError("Expected a timestamp-indexed table")
    if result.index.tz is None:
        raise ValueError("API parser returned timestamps without a timezone")
    frame = result.copy()
    frame.index = frame.index.tz_convert("UTC")
    frame = frame.loc[(frame.index >= start) & (frame.index < end)].sort_index()
    if frame.empty:
        raise ValueError("No data in the requested interval")
    if frame.index.has_duplicates:
        raise ValueError("Duplicate delivery timestamps; inspect raw responses before proceeding")
    for column in frame:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not frame[column].dropna().map(math.isfinite).all():
            raise ValueError("Nonfinite values in API data")
    frame.index.name = "delivery_start_utc"
    return frame


def main():
    """Parse download options, archive source responses and record per-dataset outcomes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-10-15", help="UTC date, inclusive")
    parser.add_argument("--end", default="2026-10-22", help="UTC date, exclusive")
    parser.add_argument(
        "--datasets", nargs="+", choices=["prices", "load", "wind_solar"], default=["prices"]
    )
    parser.add_argument("--data-dir", type=Path, default=PROJECT / "data")
    args = parser.parse_args()
    try:
        start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        if end <= start or start != start.normalize() or end != end.normalize():
            raise ValueError()
    except (ValueError, TypeError):
        parser.error(
            "Use midnight dates with end after start, e.g. --start 2026-10-15 --end 2026-10-22"
        )

    load_dotenv(PROJECT / ".env")
    token = (os.getenv("ENTSOE_API_TOKEN") or os.getenv("ENTSOE_API_KEY") or "").strip()
    if not token:
        parser.error("Set ENTSOE_API_TOKEN in your local .env; do not paste it into chat")

    # Disable library/HTTP logging that could expose authenticated URLs.
    for name in ("entsoe", "urllib3", "requests"):
        logging.getLogger(name).disabled = True
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex[:8]
    run_dir = args.data_dir.resolve() / "downloads" / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "area": "DE_LU",
        "start_utc": start.isoformat(),
        "end_utc_exclusive": end.isoformat(),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "datasets": {},
        "availability_note": "Historical forecast revisions may be returned. Document creation time is not proof of first publication or auction-time availability.",
        "processing_note": "Native parser resolution; no hourly aggregation, imputation or price transformation applied.",
    }
    methods = {
        "prices": "query_day_ahead_prices",
        "load": "query_load_forecast",
        "wind_solar": "query_wind_and_solar_forecast",
    }
    for dataset in dict.fromkeys(args.datasets):
        destination = run_dir / dataset
        raw = destination / "raw"
        raw.mkdir(parents=True)
        print(
            f"Downloading {dataset} for DE-LU: {start.date()} to {end.date()} (end exclusive)",
            flush=True,
        )
        try:
            parts = []
            with requests.Session() as session:
                session.hooks["response"].append(archive_response(raw))
                client = EntsoePandasClient(
                    api_key=token, session=session, timeout=45, retry_count=3, retry_delay=5
                )
                # Weekly chunks keep each request manageable; entsoe-py may issue extra boundary requests.
                left = start
                while left < end:
                    right = min(left + pd.Timedelta(days=7), end)
                    result = getattr(client, methods[dataset])("DE_LU", start=left, end=right)
                    part = clean_result(result, left, right)
                    # Preserve each parsed chunk even if a later request fails.
                    checkpoint = destination / "chunks"
                    checkpoint.mkdir(exist_ok=True)
                    with (checkpoint / f"{left:%Y%m%d}_{right:%Y%m%d}.csv").open(
                        "x", encoding="utf-8", newline=""
                    ) as file:
                        part.to_csv(file)
                    parts.append(part)
                    print(
                        f"  {dataset}: {left.date()} to {right.date()} saved ({len(part)} rows)",
                        flush=True,
                    )
                    left = right
            frame = pd.concat(parts).sort_index()
            if frame.index.has_duplicates:
                raise ValueError("Overlapping chunk timestamps")
            if dataset == "load" and len(frame.columns) == 1:
                frame.columns = ["load_forecast_mw"]
            # Reject unexpected price units rather than silently relabelling them.
            if dataset == "prices":
                for path in raw.glob("*.metadata.json"):
                    units = json.loads(path.read_text(encoding="utf-8"))
                    if units.get("currency_units") and units["currency_units"] != ["EUR"]:
                        raise ValueError("Unexpected price currency")
                    if units.get("measure_units") and units["measure_units"] != ["MWH"]:
                        raise ValueError("Unexpected price energy unit")
            with (destination / "native.csv").open("x", encoding="utf-8", newline="") as file:
                frame.to_csv(file)
            gaps = frame.index.to_series().diff().dropna().dt.total_seconds().div(60)
            summary = {
                "status": "success",
                "rows": len(frame),
                "columns": list(frame.columns),
                "first_delivery_start_utc": frame.index.min().isoformat(),
                "last_delivery_start_utc": frame.index.max().isoformat(),
                "missing_values": {str(c): int(v) for c, v in frame.isna().sum().items()},
                "spacing_minutes_counts": {str(k): int(v) for k, v in gaps.value_counts().items()},
                "note": "Spacing is observed timestamp spacing, not proof of complete interval coverage. Inspect raw resolution and validate coverage before modelling.",
            }
            manifest["datasets"][dataset] = summary
            print(f"Saved {len(frame)} rows to {destination / 'native.csv'}", flush=True)
        except Exception as error:
            # Exception messages/tracebacks may contain the token-bearing request URL.
            manifest["datasets"][dataset] = {"status": "failed", "error_type": type(error).__name__}
            print(
                f"{dataset} failed ({type(error).__name__}). Raw responses, if received, are preserved. Check token permissions, date range and connectivity.",
                flush=True,
            )
    manifest["status"] = (
        "success"
        if all(d["status"] == "success" for d in manifest["datasets"].values())
        else "failed"
    )
    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(run_dir / "manifest.json", manifest)
    print(f"Run status: {manifest['status']}. Manifest: {run_dir / 'manifest.json'}")
    return 0 if manifest["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
