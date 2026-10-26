"""Run repeatable local quality gates; use --with-js when Node.js is on PATH."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent


def main() -> int:
    """Stop at the first failed gate and return its exit status to the caller."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-js", action="store_true", help="Also run Node helper and syntax checks"
    )
    options = parser.parse_args()
    commands = [
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
        [sys.executable, "-m", "unittest", "discover", "-v"],
    ]
    if options.with_js:
        node = shutil.which("node")
        if node is None:
            parser.error("Node.js must be on PATH for --with-js")
        commands.extend(
            [
                [node, "test_frontend_ui.js"],
                [node, "test_dashboard_render.js"],
                [node, "test_hosted_client.js"],
                [node, "--check", "frontend/api_client.js"],
                [node, "--check", "frontend/app.js"],
                [node, "--check", "frontend/ui_helpers.js"],
            ]
        )
    for command in commands:
        print("Running: " + " ".join(command), flush=True)
        completed = subprocess.run(command, cwd=PROJECT, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
