import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "artifacts" / "artifactctl.py"


@pytest.fixture
def run():
    def _run(*args, cwd=None, env=None):
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=cwd, env=env,
                              text=True, capture_output=True)
    return _run


GOOD_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Sprint Burndown</title>
<meta name="description" content="Remaining points per day for sprint 42.">
<link rel="preconnect" href="https://fonts.gstatic.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter&display=swap">
<style>
:root { --bg: #fff; --fg: #111; --accent: #0a5 }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #111; --fg: #eee; --accent: #3c9; color-scheme: dark } }
:root[data-theme="dark"] { --bg: #111; --fg: #eee; --accent: #3c9; color-scheme: dark }
body { background: var(--bg); color: var(--fg); margin: 0; padding-block: 1rem; padding-inline: 16px }
</style></head><body>
<h1>Sprint Burndown</h1>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script>document.body.dataset.ran = "1";</script>
</body></html>
"""


@pytest.fixture
def good_page(tmp_path):
    p = tmp_path / "burndown.html"
    p.write_text(GOOD_PAGE)
    return p
