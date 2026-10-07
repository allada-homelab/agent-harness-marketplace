import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "artifacts"
sys.path.insert(0, str(SKILL))
import artifactctl  # noqa: E402

TEMPLATES = sorted((SKILL / "templates").glob("*.html"))
SIZE_BUDGET = 30 * 1024
CHROME = artifactctl.find_chrome(os.environ, shutil.which, sys.platform)
needs_chrome = pytest.mark.skipif(CHROME is None, reason="no Chrome installed")


def test_templates_exist():
    assert any(t.name == "tool.html" for t in TEMPLATES), TEMPLATES


@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: p.name)
def test_template_passes_check(tpl):
    fails, warns = artifactctl.check_html(tpl.read_text(), tpl.stat().st_size)
    assert fails == [] and warns == [], fails + warns


@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: p.name)
def test_template_header_names_itself(tpl):
    text = tpl.read_text()
    m = re.match(r"\s*<!doctype html>\s*<!-- template: ([\w-]+) · slots: ([^>]*?)-->", text, re.I)
    assert m, "the line after <!doctype html> must be <!-- template: <name> · slots: ... -->"
    assert m.group(1) == tpl.stem
    slots = [s.strip() for s in m.group(2).split(",")]
    assert slots[:2] == ["title", "description"] and "DATA" in slots, slots


@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: p.name)
def test_template_has_title_slot_and_data(tpl):
    text = tpl.read_text()
    assert 'data-slot="title"' in text
    assert re.search(r"\bconst DATA = \{", text)
    assert len(re.findall(r"<script\b(?![^>]*\bsrc=)[^>]*>", text, re.I)) == 1, "one inline <script>"


@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: p.name)
def test_template_size_budget(tpl):
    assert tpl.stat().st_size <= SIZE_BUDGET, f"{tpl.stat().st_size} bytes > {SIZE_BUDGET}"


@needs_chrome
@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: p.name)
def test_template_renders_clean(tpl, tmp_path):
    r = subprocess.run([sys.executable, "-I", str(SKILL / "artifactctl.py"), "render", str(tpl),
                        "--out", str(tmp_path / f"{tpl.stem}.png")], text=True, capture_output=True)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[-1] == "ok" and not [l for l in lines if l.startswith("WARN console")], r.stdout


# ── tool.html inside dsh's real frame: sandbox="allow-scripts", nothing else ──

PROBE = """<script>
(() => {
  const count = () => document.querySelectorAll("#entries > li[data-id]").length;
  const fill = (label) => {
    document.getElementById("entry-label").value = label;
    document.getElementById("entry-amount").value = "12.40";
    document.getElementById("entry-date").value = "2026-09-17";
  };
  const before = count();
  fill("Probe by click");
  document.getElementById("entry-add").click();
  const afterClick = count();
  fill("Probe by Enter");
  document.getElementById("entry-amount").dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  const afterEnter = count();
  document.getElementById("entry-amount").value = "";
  document.getElementById("entry-add").click();
  const afterInvalid = count();
  parent.postMessage({ before, afterClick, afterEnter, afterInvalid }, "*");
})();
</script>"""

HOST = """<!doctype html><html><head><meta charset="utf-8"><title>pending</title></head><body>
<script>window.addEventListener("message", e => { document.title = "result:" + JSON.stringify(e.data); });</script>
<iframe sandbox="allow-scripts" width="390" height="844" srcdoc="{srcdoc}"></iframe>
</body></html>"""


@needs_chrome
def test_tool_adds_rows_inside_allow_scripts_sandbox(tmp_path):
    inner = (SKILL / "templates" / "tool.html").read_text().replace("</body>", PROBE + "</body>")
    host = tmp_path / "host.html"
    host.write_text(HOST.replace("{srcdoc}", html.escape(inner, quote=True)))
    profile = tempfile.mkdtemp()
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           f"--user-data-dir={profile}", "--virtual-time-budget=5000", "--dump-dom", host.as_uri()]
    if os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    try:
        dom = subprocess.run(cmd, text=True, capture_output=True, timeout=60).stdout
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    m = re.search(r"<title>result:(.*?)</title>", dom)
    assert m, "the probe never reported; tool.html threw or its controls are missing:\n" + dom[:400]
    r = json.loads(html.unescape(m.group(1)))
    assert r["before"] > 0, r  # opens in a working state with sample rows
    assert r["afterClick"] == r["before"] + 1, r
    assert r["afterEnter"] == r["afterClick"] + 1, r
    assert r["afterInvalid"] == r["afterEnter"], r  # an empty amount is refused inline
