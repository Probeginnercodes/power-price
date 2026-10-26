import io
import json
import unittest
from unittest.mock import patch

from serve import Handler


class FrontendHandlerTests(unittest.TestCase):
    def handler(self, path="/", headers=None, body=b""):
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = headers or {}
        handler.rfile = io.BytesIO(body)
        handler.replies = []
        handler.reply = (
            lambda status, payload, content_type="application/json": handler.replies.append(
                (status, payload, content_type)
            )
        )
        return handler

    def test_homepage_is_served(self):
        h = self.handler()
        h.do_GET()
        self.assertEqual(h.replies[0][0], 200)
        self.assertIn(b"Power Forecast Lab", h.replies[0][1])

    def test_separate_unit_charts_and_labels_exist(self):
        from html.parser import HTMLParser

        class Tags(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = []
                self.scripts = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if "id" in attrs:
                    self.ids.append(attrs["id"])
                if tag == "script" and "src" in attrs:
                    self.scripts.append(attrs["src"])

        h = self.handler()
        h.do_GET()
        parser = Tags()
        parser.feed(h.replies[0][1].decode("utf-8-sig"))
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for name in ["dispatchchart", "energychart", "coverage-status", "battery-period"]:
            self.assertIn(name, parser.ids)
        self.assertLess(parser.scripts.index("./ui_helpers.js"), parser.scripts.index("./app.js"))

    def test_ui_helpers_route_is_served(self):
        h = self.handler("/ui_helpers.js")
        h.do_GET()
        self.assertEqual(h.replies[0][0], 200)
        self.assertIn(b"coverageStatus", h.replies[0][1])

    def test_secret_files_are_not_served(self):
        for path in ["/.env", "/../.env", "/api/download?run=..&file=.env"]:
            h = self.handler(path)
            h.do_GET()
            self.assertNotEqual(h.replies[0][0], 200)

    def test_foreign_origin_cannot_start_jobs(self):
        h = self.handler("/api/run", {"Origin": "https://example.com"})
        h.do_POST()
        self.assertEqual(h.replies[0][0], 403)

    def test_local_job_request_is_validated_and_accepted(self):
        body = json.dumps({"mode": "demo", "days": 1}).encode()
        h = self.handler(
            "/api/run", {"Origin": "http://127.0.0.1:8765", "Content-Length": str(len(body))}, body
        )
        with patch("serve.launch") as launch:
            h.do_POST()
            self.assertEqual(h.replies[0][0], 202)
            launch.assert_called_once()

    def test_invalid_json_rejected(self):
        h = self.handler(
            "/api/run", {"Origin": "http://127.0.0.1:8765", "Content-Length": "1"}, b"{"
        )
        h.do_POST()
        self.assertEqual(h.replies[0][0], 400)

    def test_status_contains_no_token(self):
        h = self.handler("/api/status")
        h.do_GET()
        self.assertEqual(h.replies[0][0], 200)
        self.assertNotIn("ENTSOE_API_TOKEN", json.dumps(h.replies[0][1]))


if __name__ == "__main__":
    unittest.main()
