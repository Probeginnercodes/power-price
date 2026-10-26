"""Build GitHub Pages assets without publishing or embedding backend credentials."""

import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

PROJECT = Path(__file__).resolve().parent


def build_pages(api_url: str, output: Path) -> None:
    url = urlsplit(api_url)
    if (
        url.scheme != "https"
        or not url.netloc
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        raise ValueError("Provide an HTTPS backend origin without credentials, path or query")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "api_client.js", "ui_helpers.js", "style.css"):
        shutil.copy2(PROJECT / "frontend" / name, output / name)
    (output / "config.js").write_text(
        "window.FORECAST_CONFIG = "
        + json.dumps({"hosted": True, "apiBase": api_url.rstrip("/")})
        + ";\n",
        encoding="utf-8",
    )
    (output / ".nojekyll").touch()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--output", type=Path, default=PROJECT / "pages-dist")
    args = parser.parse_args()
    build_pages(args.api_url, args.output)
    print(args.output)
