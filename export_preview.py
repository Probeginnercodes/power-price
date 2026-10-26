"""Export a self-contained read-only dashboard snapshot, without a running server."""

import argparse
import csv
import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent


def main():
    """Embed saved results and frontend assets into a read-only HTML snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    paths = (
        [PROJECT / "data" / "results" / args.run_id / "results.json"]
        if args.run_id
        else sorted((PROJECT / "data" / "results").glob("*/results.json"), reverse=True)
    )
    if not paths:
        raise ValueError("No completed run")
    folder = paths[0].parent
    report = json.loads(paths[0].read_text(encoding="utf-8"))
    result = {"report": report}
    for name in ["forecasts", "battery_values", "battery_dispatch", "metrics_by_hour"]:
        with (folder / f"{name}.csv").open(encoding="utf-8", newline="") as file:
            result[name] = list(csv.DictReader(file))
    sensitivity_paths = [folder / "sensitivity.csv"]
    sensitivity_paths += sorted(
        (PROJECT / "data" / "sensitivity").glob(folder.name + "_*/sensitivity.csv"),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    for sensitivity_path in sensitivity_paths:
        if sensitivity_path.is_file():
            with sensitivity_path.open(encoding="utf-8", newline="") as sensitivity_file:
                result["sensitivity"] = list(csv.DictReader(sensitivity_file))
            break
    status = {
        "job": {"running": False, "status": "read-only snapshot"},
        "log": "Read-only exported result. Start python serve.py for interactive experiments.",
        "runs": [{"id": folder.name, "mode": report["mode"], "status": "success"}],
        "datasets": [
            {
                "id": folder.name,
                "hours": report["forecast_hours"],
                "start": report["forecast_days"][0],
                "end": report["forecast_days"][-1],
            }
        ],
    }
    trial_summary = PROJECT / "data" / "research" / "trial_summary.json"
    if trial_summary.is_file():
        status["research"] = json.loads(trial_summary.read_text(encoding="utf-8"))
    payload = json.dumps({"result": result, "status": status}, allow_nan=False).replace(
        "<", "\\u003c"
    )
    shim = (
        "const SNAPSHOT="
        + payload
        + '; window.fetch=async function(url,options){ if(options&&options.method==="POST")return new Response(JSON.stringify({error:"Read-only preview. Start python serve.py to run experiments."}),{status:400});const data=String(url).startsWith("/api/result/")?SNAPSHOT.result:SNAPSHOT.status;return new Response(JSON.stringify(data),{status:200});};'
    )
    template = (PROJECT / "frontend" / "index.html").read_text(encoding="utf-8-sig")
    template = re.sub(r'<script src="\./(?:config|api_client)\.js"></script>', "", template)
    css = (PROJECT / "frontend" / "style.css").read_text(encoding="utf-8-sig")
    js = (PROJECT / "frontend" / "app.js").read_text(encoding="utf-8-sig")
    html = re.sub(
        r'<link\s+rel="stylesheet"\s+href="[./]*style\.css"\s*/?>',
        lambda match: "<style>" + css + "</style>",
        template,
    )
    html = html.replace(
        '<script src="./ui_helpers.js"></script>',
        "<script>"
        + (PROJECT / "frontend" / "ui_helpers.js").read_text(encoding="utf-8-sig")
        + "</script>",
    )
    html = html.replace(
        '<script src="./app.js"></script>',
        "<script>" + shim + "</script><script>" + js + "</script>",
    )
    html = html.replace(
        "<title>Power Forecast Lab</title>", "<title>Power Forecast Lab — read-only result</title>"
    )
    # API artifact links need the running server; remove them from static snapshots.
    html = html.replace("</style>", ".downloads{display:none}</style>")
    out = PROJECT / "data" / "previews"
    out.mkdir(parents=True, exist_ok=True)
    path = out / (folder.name + ".html")
    path.write_text(html, encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
