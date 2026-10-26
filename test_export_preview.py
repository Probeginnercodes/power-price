"""The read-only export must remain self-contained after frontend formatting."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import export_preview


class AssetReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.local_assets = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "script" and "src" in attributes:
            self.local_assets.append(attributes["src"])
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.local_assets.append(attributes["href"])


class SnapshotTests(unittest.TestCase):
    def test_formatted_assets_are_embedded_without_server_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            shutil.copytree(Path(__file__).parent / "frontend", project / "frontend")
            result_directory = project / "data" / "results" / "example"
            result_directory.mkdir(parents=True)
            report = {"mode": "demo", "forecast_hours": 24, "forecast_days": ["2026-01-01"]}
            (result_directory / "results.json").write_text(json.dumps(report), encoding="utf-8")
            for name in ("forecasts", "battery_values", "battery_dispatch", "metrics_by_hour"):
                (result_directory / f"{name}.csv").write_text("example\n1\n", encoding="utf-8")
            with (
                patch.object(export_preview, "PROJECT", project),
                patch("sys.argv", ["export_preview.py"]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                export_preview.main()
            snapshot = (project / "data" / "previews" / "example.html").read_text(encoding="utf-8")
            parser = AssetReferences()
            parser.feed(snapshot)
            self.assertEqual(parser.local_assets, [])
            self.assertIn("const SNAPSHOT=", snapshot)
            self.assertIn("coverageStatus", snapshot)
            self.assertIn("<style>", snapshot)


if __name__ == "__main__":
    unittest.main()
