import html
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "artifacts"))
import artifactctl  # noqa: E402

# Sibling modules each have a conftest.py; `import conftest` would resolve to whichever pytest
# put on sys.path first when all module suites run in one session, so load ours by path.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("artifacts_conftest", Path(__file__).with_name("conftest.py"))
_conf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_conf)
GOOD_PAGE = _conf.GOOD_PAGE


# ── check ────────────────────────────────────────────────────────────────

def test_check_passes_good_page(run, good_page):
    r = run("check", str(good_page))
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == f"ok {good_page}"


def test_check_missing_file_is_usage_error(run, tmp_path):
    r = run("check", str(tmp_path / "nope.html"))
    assert r.returncode == 2
    assert "nope.html" in r.stderr


@pytest.mark.parametrize("mutation, rule", [
    (lambda t: t.replace("<!doctype html>\n", ""), "doctype"),
    (lambda t: t.replace("<title>Sprint Burndown</title>", ""), "title"),
    (lambda t: t.replace("<title>Sprint Burndown</title>", "<title>" + "x" * 61 + "</title>"), "title"),
    (lambda t: t.replace('<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n', ""), "viewport"),
    (lambda t: t.replace(":root { --bg: #fff; --fg: #111; --accent: #0a5 }\n", ""), "tokens"),
    (lambda t: t + "<script>window.claude.use('db')</script>", "forbidden"),
    (lambda t: t + '<a href="https://claude.ai/artifact/x">x</a>', "forbidden"),
    (lambda t: t + "<!-- ArtifactData seeds this -->", "forbidden"),
])
def test_check_fails_each_rule_once(mutation, rule):
    fails, _ = artifactctl.check_html(mutation(GOOD_PAGE), size=1024)
    assert [f for f in fails if f.startswith(rule)], fails
    assert len(fails) == 1, fails


def test_check_rejects_foreign_script_host():
    page = GOOD_PAGE + '<script type="module" src="https://esm.sh/preact"></script>'
    fails, _ = artifactctl.check_html(page, size=1024)
    assert fails == ["host: script from https://esm.sh/preact is not on the CDN allowlist"]


def test_check_rejects_jsdelivr_outside_npm():
    page = GOOD_PAGE + '<script src="https://cdn.jsdelivr.net/gh/user/repo/x.js"></script>'
    fails, _ = artifactctl.check_html(page, size=1024)
    assert len(fails) == 1 and fails[0].startswith("host:")


def test_check_allows_every_allowlisted_script_host():
    hosts = ["https://cdnjs.cloudflare.com/ajax/libs/x/1/x.js", "https://cdn.jsdelivr.net/npm/x@1/x.js",
             "https://unpkg.com/x@1/x.js", "https://cdn.tailwindcss.com", "https://code.jquery.com/jquery-3.7.1.min.js"]
    page = GOOD_PAGE + "".join(f'<script src="{h}"></script>' for h in hosts)
    fails, _ = artifactctl.check_html(page, size=1024)
    assert fails == []


def test_check_allows_preconnect_and_google_fonts():
    # GOOD_PAGE already carries a preconnect to fonts.gstatic.com and a Google Fonts stylesheet.
    fails, _ = artifactctl.check_html(GOOD_PAGE, size=1024)
    assert fails == []


def test_check_rejects_foreign_stylesheet_host():
    page = GOOD_PAGE + '<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/x/1/x.css">'
    fails, _ = artifactctl.check_html(page, size=1024)
    assert fails == ["host: stylesheet from https://cdnjs.cloudflare.com/ajax/libs/x/1/x.css is not fonts.googleapis.com"]


def test_check_inline_script_and_style_pass():
    page = GOOD_PAGE + "<script>var a = 1;</script><style>p { margin: 0 }</style>"
    fails, _ = artifactctl.check_html(page, size=1024)
    assert fails == []


def _only(page, prefix):
    fails, _ = artifactctl.check_html(page, size=1024)
    assert len(fails) == 1 and fails[0].startswith(prefix), fails


def _none(page):
    fails, _ = artifactctl.check_html(page, size=1024)
    assert fails == [], fails


def test_good_page_has_no_failures():
    _none(GOOD_PAGE)


def test_check_fails_relative_script_src():
    _only(GOOD_PAGE + '<script src="app.js"></script>', "local: script references a local file")


def test_check_fails_relative_stylesheet_href():
    _only(GOOD_PAGE + '<link rel="stylesheet" href="style.css">', "local: stylesheet references a local file")


def test_check_fails_empty_script_src():
    _only(GOOD_PAGE + '<script src=""></script>', "local: script references a local file")


@pytest.mark.parametrize("body", [
    'import {h} from "https://esm.sh/preact"',
    "import {h} from 'https://esm.sh/preact'",
    'import "https://esm.sh/preact"',
    'const m = await import("https://esm.sh/preact")',
    "const m = await import('https://esm.sh/preact')",
])
def test_check_fails_foreign_inline_module_import(body):
    _only(GOOD_PAGE + f'<script type="module">{body}</script>', "host: import from https://esm.sh/preact")


def test_check_allows_allowlisted_inline_module_import():
    _none(GOOD_PAGE + '<script type="module">import "https://cdn.jsdelivr.net/npm/preact@10/dist/preact.module.js"</script>')


@pytest.mark.parametrize("body", ['import {h} from "./x.js"', 'import "preact"', 'import("./x.js")'])
def test_check_fails_local_inline_module_import(body):
    _only(GOOD_PAGE + f'<script type="module">{body}</script>', "local: import references a local file")


def test_check_fails_foreign_css_import():
    _only(GOOD_PAGE + '<style>@import url("https://cdnjs.cloudflare.com/x.css")</style>',
          "host: @import from https://cdnjs.cloudflare.com/x.css is not fonts.googleapis.com")


@pytest.mark.parametrize("rule", [
    '@import "https://fonts.googleapis.com/css2?family=Inter";',
    "@import url(https://fonts.googleapis.com/css2?family=Inter);",
])
def test_check_allows_google_fonts_css_import(rule):
    _none(GOOD_PAGE + f"<style>{rule}</style>")


def test_check_fails_local_css_import():
    _only(GOOD_PAGE + '<style>@import "theme.css"</style>', "local: @import references a local file")


def test_check_modulepreload_host_is_checked():
    _only(GOOD_PAGE + '<link rel="modulepreload" href="https://esm.sh/x">', "host: modulepreload from https://esm.sh/x")
    _none(GOOD_PAGE + '<link rel="modulepreload" href="https://unpkg.com/x/y.js">')
    _only(GOOD_PAGE + '<link rel="modulepreload" href="x.js">', "local: modulepreload references a local file")


def test_check_rejects_jsdelivr_npm_path_traversal():
    _only(GOOD_PAGE + '<script src="https://cdn.jsdelivr.net/npm/../gh/u/r/x.js"></script>', "host: script from ")


def test_check_is_case_and_whitespace_tolerant():
    page = "﻿" + GOOD_PAGE.replace("<!doctype html>", "<!DOCTYPE HTML>").replace(
        "<title>Sprint Burndown</title>", "<TITLE>\n  Sprint Burndown\n</TITLE>")
    fails, _ = artifactctl.check_html(page, size=1024)
    assert fails == []


def test_check_size_cap():
    fails, _ = artifactctl.check_html(GOOD_PAGE, size=16 * 1024 * 1024 + 1)
    assert fails == ["size: 16777217 bytes exceeds the 16 MB cap"]
    fails, _ = artifactctl.check_html(GOOD_PAGE, size=16 * 1024 * 1024)
    assert fails == []


def test_check_warns_without_failing_on_single_theme():
    page = GOOD_PAGE.replace(
        '@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg: #111; --fg: #eee; --accent: #3c9; color-scheme: dark } }\n', "").replace(
        ':root[data-theme="dark"] { --bg: #111; --fg: #eee; --accent: #3c9; color-scheme: dark }\n', "")
    fails, warns = artifactctl.check_html(page, size=1024)
    assert fails == []
    assert warns == ["theme: no dark-mode rule; fine only for a deliberately single-theme design"]


def test_check_cli_prints_each_failure(run, tmp_path):
    p = tmp_path / "bad.html"
    p.write_text("<p>hi</p>")
    r = run("check", str(p))
    assert r.returncode == 1
    lines = r.stdout.strip().splitlines()
    assert all(l.startswith("FAIL ") for l in lines)
    assert {l.split(":")[0] for l in lines} == {"FAIL doctype", "FAIL title", "FAIL viewport", "FAIL tokens"}


# ── prepare ──────────────────────────────────────────────────────────────

def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git("init", "-q", "-b", "main", cwd=root)
    git("config", "user.email", "t@example.com", cwd=root)
    git("config", "user.name", "t", cwd=root)
    (root / "README.md").write_text("hi\n")
    git("add", "README.md", cwd=root)
    git("commit", "-q", "-m", "init", cwd=root)
    return root


def test_prepare_defaults_to_cache_per_project(run, repo, tmp_path):
    cache = tmp_path / "cache"
    r = run("prepare", cwd=repo, env={"XDG_CACHE_HOME": str(cache), "PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(cache / "agent-artifacts" / "repo")
    assert (cache / "agent-artifacts" / "repo").is_dir()
    assert not (repo / ".artifacts").exists()
    assert git("status", "--porcelain", cwd=repo) == ""


def test_prepare_env_root_wins_and_worktree_shares_project(run, repo, tmp_path):
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "feat", str(wt), cwd=repo)
    root = tmp_path / "elsewhere"
    env = {"AGENT_ARTIFACTS_DIR": str(root), "XDG_CACHE_HOME": str(tmp_path / "unused"),
           "PATH": os.environ["PATH"]}
    r = run("prepare", cwd=wt, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(root / "repo")  # the main checkout's name, not "wt"
    assert run("prepare", cwd=repo, env=env).stdout.strip() == str(root / "repo")


def test_prepare_outside_git_uses_dir_name(run, tmp_path):
    proj = tmp_path / "notes"
    proj.mkdir()
    r = run("prepare", cwd=proj, env={"XDG_CACHE_HOME": str(tmp_path / "c"), "PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(tmp_path / "c" / "agent-artifacts" / "notes")


def test_prepare_here_creates_dir_and_excludes_it(run, repo):
    r = run("prepare", "--here", cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(repo / ".artifacts")
    assert (repo / ".artifacts").is_dir()
    assert ".artifacts/\n" in (repo / ".git" / "info" / "exclude").read_text()
    # idempotent
    run("prepare", "--here", cwd=repo)
    assert (repo / ".git" / "info" / "exclude").read_text().count(".artifacts/\n") == 1
    assert git("status", "--porcelain", cwd=repo) == ""


def test_prepare_here_excludes_in_worktree(run, repo, tmp_path):
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "feat", str(wt), cwd=repo)
    r = run("prepare", "--here", cwd=wt)
    assert r.returncode == 0, r.stderr
    assert (wt / ".artifacts").is_dir()
    assert ".artifacts/\n" in (repo / ".git" / "info" / "exclude").read_text()
    assert not (wt / ".git" / "info").exists()  # .git is a file here; nothing was written beside it


def test_prepare_here_outside_git(run, tmp_path):
    r = run("prepare", "--here", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".artifacts").is_dir()


def test_prepare_here_takes_explicit_dir(run, repo):
    sub = repo / "docs"
    sub.mkdir()
    r = run("prepare", str(sub), "--here", cwd=repo)
    assert r.stdout.strip() == str(sub / ".artifacts")


# ── open ─────────────────────────────────────────────────────────────────

def test_display_detection():
    assert artifactctl.is_display_available({"DISPLAY": ":0"}, "linux")
    assert artifactctl.is_display_available({"WAYLAND_DISPLAY": "wayland-0"}, "linux")
    assert artifactctl.is_display_available({}, "darwin")
    assert not artifactctl.is_display_available({}, "linux")


def test_open_prints_path_without_display(run, good_page):
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env["ARTIFACTCTL_PLATFORM"] = "linux"
    r = run("open", str(good_page), env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(good_page.resolve())


def test_open_launches_opener_when_display(run, good_page, tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "opened.log"
    (fake / "xdg-open").write_text(f"#!/bin/sh\necho \"$1\" >> {log}\n")
    (fake / "xdg-open").chmod(0o755)
    env = dict(os.environ, DISPLAY=":0", PATH=f"{fake}:{os.environ['PATH']}", ARTIFACTCTL_PLATFORM="linux")
    r = run("open", str(good_page), env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(good_page.resolve())
    assert log.read_text().strip() == str(good_page.resolve())


def test_open_missing_file(run, tmp_path):
    r = run("open", str(tmp_path / "x.html"))
    assert r.returncode == 2


# ── sandbox: form submission never fires in dsh's allow-scripts-only frame ──

SANDBOX_TAIL = ' — form submission never fires in the dsh preview (sandbox lacks allow-forms); ' \
               'use type="button" with a click handler and Enter on keydown'


@pytest.mark.parametrize("snippet", [
    '<script>f.addEventListener("submit", e => e.preventDefault())</script>',
    "<script>f.addEventListener( 'submit', add)</script>",
    "<script>document.forms[0].onsubmit = add</script>",
    '<form onsubmit="add(); return false"><input id="a"></form>',
    '<form action="/add"><input id="a"></form>',
    "<form method=post><input id=\"a\"></form>",
    '<form><button type="submit">Add</button></form>',
    "<form><button class=x type='submit'>Add</button></form>",
    "<form><input type=submit value=Add></form>",
])
def test_check_fails_form_submission(snippet):
    fails, _ = artifactctl.check_html(GOOD_PAGE.replace("</body>", snippet + "</body>"), size=1024)
    assert len(fails) == 1, fails
    assert fails[0].startswith("sandbox: ") and fails[0].endswith(SANDBOX_TAIL), fails


def test_check_reports_each_submission_hit():
    snippet = '<form method="post"><button type="submit">Add</button></form>' \
              '<script>document.querySelector("form").addEventListener("submit", add)</script>'
    fails, _ = artifactctl.check_html(GOOD_PAGE.replace("</body>", snippet + "</body>"), size=1024)
    assert len(fails) == 3 and all(f.startswith("sandbox: ") for f in fails), fails


def test_check_passes_button_form_with_keydown():
    snippet = ('<form id="f"><label for="a">Item</label><input id="a">'
               '<button type="button" id="add">Add</button></form>'
               '<script>const add = () => {};'
               'document.getElementById("add").addEventListener("click", add);'
               'document.getElementById("a").addEventListener("keydown", e => { if (e.key === "Enter") add(); });'
               '</script>')
    fails, _ = artifactctl.check_html(GOOD_PAGE.replace("</body>", snippet + "</body>"), size=1024)
    assert fails == []


@pytest.mark.parametrize("snippet, n", [
    ('<form data-action="x"><input id="a"></form>', 0),
    ('<form action="x"><input id="a"></form>', 1),
    ('<form><button data-type="submit" type="button">Add</button></form>', 0),
    ('<form><button type="submit">Add</button></form>', 1),
])
def test_check_sandbox_ignores_data_attributes(snippet, n):
    fails, _ = artifactctl.check_html(GOOD_PAGE.replace("</body>", snippet + "</body>"), size=1024)
    assert len(fails) == n, fails


@pytest.mark.parametrize("snippet, n", [
    ('<pre><code>form.addEventListener("submit", f)</code></pre>', 0),
    ('<pre><code>form.addEventListener("submit", f)</code></pre><script>form.addEventListener("submit", f)</script>', 1),
])
def test_check_sandbox_ignores_code_samples(snippet, n):
    fails, _ = artifactctl.check_html(GOOD_PAGE.replace("</body>", snippet + "</body>"), size=1024)
    assert len(fails) == n, fails


# ── allowlist bypass forms ───────────────────────────────────────────────

@pytest.mark.parametrize("tag, kind", [
    ('<script src=https://esm.sh/x.js></script>', "script"),
    ("<script src='https://esm.sh/x.js'></script>", "script"),
    ('<script src="data:text/javascript,alert(1)"></script>', "script"),
    ('<script src="https:\\\\evil.example/x.js"></script>', "script"),
    ('<link rel=stylesheet href=https://evil.example/x.css>', "stylesheet"),
])
def test_check_closes_allowlist_bypass_forms(tag, kind):
    fails, _ = artifactctl.check_html(GOOD_PAGE + tag, size=1024)
    assert len(fails) == 1 and fails[0].startswith(f"host: {kind} from "), fails


def test_check_allows_unquoted_allowlisted_script():
    fails, _ = artifactctl.check_html(
        GOOD_PAGE + "<script src=https://cdnjs.cloudflare.com/ajax/libs/x/1/x.js></script>", size=1024)
    assert fails == []


# ── render ───────────────────────────────────────────────────────────────

DARWIN_APP = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def test_find_chrome_env_override_wins():
    env = {"ARTIFACTS_CHROME": "/x/chrome"}
    assert artifactctl.find_chrome(env, lambda n: "/usr/bin/" + n, "linux") == "/x/chrome"


def test_find_chrome_path_order():
    found = {"chromium": "/usr/bin/chromium", "chrome": "/usr/bin/chrome"}
    assert artifactctl.find_chrome({}, found.get, "linux") == "/usr/bin/chromium"


def test_find_chrome_darwin_app_path():
    assert artifactctl.find_chrome({}, lambda n: None, "darwin", exists=lambda p: p == DARWIN_APP) == DARWIN_APP
    assert artifactctl.find_chrome({}, lambda n: None, "linux", exists=lambda p: True) is None


def test_find_chrome_none():
    assert artifactctl.find_chrome({}, lambda n: None, "darwin", exists=lambda p: False) is None


def test_parse_console_splits_fail_and_warn():
    err = (
        "noise line\n"
        '[2846483:2846483:1007/135324.422582:INFO:CONSOLE:1] "boom-console", source: file:///tmp/x/throws.html (1)\n'
        '[2846483:2846483:1007/135324.431099:INFO:CONSOLE:1] "Uncaught ReferenceError: nope is not defined", source: file:///tmp/x/throws.html (1)\n'
    )
    assert artifactctl.parse_console(err) == (
        ["console: Uncaught ReferenceError: nope is not defined"], ["console: boom-console"])


def test_parse_console_ignores_noise():
    assert artifactctl.parse_console("DevTools listening\n[1:1:ERROR:gpu] nope\n") == ([], [])


def test_render_without_chrome_is_skipped(run, good_page, monkeypatch):
    monkeypatch.delenv("ARTIFACTS_CHROME", raising=False)
    r = run("render", str(good_page), env={"PATH": ""})
    assert r.returncode == 0 and r.stdout.startswith("skipped:"), r.stdout + r.stderr


def test_render_missing_override_is_usage_error(run, good_page):
    r = run("render", str(good_page), env={"PATH": "", "ARTIFACTS_CHROME": "/nonexistent/chrome"})
    assert r.returncode == 2
    assert "ARTIFACTS_CHROME=/nonexistent/chrome does not exist" in r.stdout + r.stderr


needs_chrome = pytest.mark.skipif(artifactctl.find_chrome(os.environ, shutil.which, sys.platform) is None,
                                  reason="no Chrome installed")


@needs_chrome
def test_render_good_page_writes_png(run, tmp_path):
    p = tmp_path / "good.html"
    p.write_text(GOOD_PAGE)
    r = run("render", str(p), env=dict(os.environ))
    assert r.returncode == 0, r.stdout + r.stderr
    png = tmp_path / "good.png"
    assert png.is_file() and png.stat().st_size > 0
    lines = r.stdout.strip().splitlines()
    assert lines[0] == f"rendered {png}" and lines[-1] == "ok"


@needs_chrome
def test_render_reports_uncaught_error(run, tmp_path):
    p = tmp_path / "bad.html"
    p.write_text(GOOD_PAGE.replace("</body>", "<script>nope()</script></body>"))
    r = run("render", str(p), env=dict(os.environ))
    assert r.returncode == 1, r.stdout + r.stderr
    assert any(l.startswith("FAIL console: Uncaught ReferenceError") for l in r.stdout.splitlines())
    assert r.stdout.strip().splitlines()[-1] == "fail"


@needs_chrome
def test_render_sandbox_reports_error_inside_frame(run, tmp_path):
    p = tmp_path / "bad.html"
    p.write_text(GOOD_PAGE.replace("</body>", "<script>nope()</script></body>"))
    r = run("render", str(p), "--sandbox", env=dict(os.environ))
    assert r.returncode == 1, r.stdout + r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[0] == f"rendered {tmp_path / 'bad.png'} (sandbox)"
    assert any(l.startswith("FAIL console:") and "nope" in l for l in lines), r.stdout
    assert lines[-1] == "fail"


@needs_chrome
def test_render_sandbox_surfaces_unguarded_storage(run, tmp_path):
    p = tmp_path / "store.html"
    p.write_text(GOOD_PAGE.replace("</body>", '<script>localStorage.getItem("k")</script></body>'))
    r = run("render", str(p), "--sandbox", env=dict(os.environ))
    assert r.returncode == 1, r.stdout + r.stderr
    assert any(l.startswith("FAIL console:") and "localStorage" in l for l in r.stdout.splitlines()), r.stdout
    r = run("render", str(p), env=dict(os.environ))
    assert r.returncode == 0, r.stdout + r.stderr


@needs_chrome
def test_render_sandbox_good_page_ok(run, tmp_path):
    p = tmp_path / "good.html"
    p.write_text(GOOD_PAGE)
    r = run("render", str(p), "--sandbox", env=dict(os.environ))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "good.png").stat().st_size > 0
    assert r.stdout.strip().splitlines()[-1] == "ok"


@needs_chrome
@pytest.mark.parametrize("delay", [1000, 2500])
def test_render_sandbox_reports_deferred_error(run, tmp_path, delay):
    p = tmp_path / "late.html"
    p.write_text(GOOD_PAGE.replace(
        "</body>", f'<script>setTimeout(() => {{ throw new Error("late{delay}") }}, {delay})</script></body>'))
    r = run("render", str(p), "--sandbox", env=dict(os.environ))
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"FAIL console: Uncaught Error: late{delay}" in r.stdout.splitlines(), r.stdout


@needs_chrome
def test_render_sandbox_reports_rejection_once(run, tmp_path):
    p = tmp_path / "rej.html"
    p.write_text(GOOD_PAGE.replace("</body>", '<script>Promise.reject(new Error("rej"))</script></body>'))
    r = run("render", str(p), "--sandbox", env=dict(os.environ))
    assert r.returncode == 1, r.stdout + r.stderr
    assert [l for l in r.stdout.splitlines() if l.startswith("FAIL console:")] == [
        "FAIL console: Uncaught (in promise) Error: rej"], r.stdout


def test_sandbox_host_escapes_inner_and_probes_once():
    host = artifactctl.sandbox_host(GOOD_PAGE)
    assert '<iframe sandbox="allow-scripts" srcdoc="' in host
    srcdoc = host.split('srcdoc="', 1)[1].split('"', 1)[0]
    assert "&lt;script" in srcdoc and "<" not in srcdoc
    assert host.count("unhandledrejection") == 1
    # the probe lands at the top of the inner <head>, before the page's own markup
    assert srcdoc.index("unhandledrejection") < srcdoc.index("&lt;meta charset")


@pytest.mark.parametrize("page, after", [
    ("<!doctype html><title>T</title><p>x", "<!doctype html>"),
    ('<!doctype html><html lang="en"><title>T</title><p>x', '<html lang="en">'),
])
def test_sandbox_host_probe_follows_doctype_without_head(page, after):
    srcdoc = html.unescape(artifactctl.sandbox_host(page).split('srcdoc="', 1)[1].split('"', 1)[0])
    assert srcdoc.startswith("<!doctype html>")
    assert srcdoc.index("unhandledrejection") > srcdoc.index(after)


# ── theme: color literals outside the token blocks ───────────────────────

def _theme_warns(css):
    _, warns = artifactctl.check_html(GOOD_PAGE.replace("</style>", css + "\n</style>"), size=1024)
    return [w for w in warns if w.startswith("theme:")]


@pytest.mark.parametrize("css", [
    ":root { --card: #333; --shade: rgb(0 0 0 / 0.2) }",
    '@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --card: #ccc; --x: oklch(70% 0.1 200) } }',
    ".hero { background: url(data:image/png;base64,AAAA#notacolor) }",
    ".hero { color-scheme: dark }",
    "/* .card { color: #333 } */ .card { color: var(--fg) }",
])
def test_check_theme_allows_tokens_and_non_colors(css):
    assert _theme_warns(css) == []


def test_check_theme_warns_literal_outside_tokens():
    fails, warns = artifactctl.check_html(GOOD_PAGE.replace("</style>", ".card{color:#333}\n</style>"), size=1024)
    assert fails == []
    assert warns == ['theme: color literal #333 in rule ".card" — define it as a token on :root so both themes stay readable']


def test_check_theme_warns_functions_and_caps_at_ten():
    assert _theme_warns(".a { border: 1px solid color-mix(in srgb, var(--fg) 20%, transparent) }") == [
        'theme: color literal color-mix(in srgb, var(--fg) 20%, transparent) in rule ".a" — '
        "define it as a token on :root so both themes stay readable"]
    assert len(_theme_warns("".join(f".c{i} {{ color: rgba(0,0,0,.{i}) }}" for i in range(15)))) == 10


def test_good_page_has_no_theme_warnings():
    _, warns = artifactctl.check_html(GOOD_PAGE, size=1024)
    assert warns == []


def test_check_theme_skips_escaped_quote():
    assert _theme_warns('.a::after{content:"\\"";} .b{color:#123}') == [
        'theme: color literal #123 in rule ".b" — define it as a token on :root so both themes stay readable']


def test_check_theme_ignores_quoted_strings():
    assert _theme_warns('.a::after{content:"#add"}') == []
