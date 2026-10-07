import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "artifacts"))
import artifactctl  # noqa: E402

from conftest import GOOD_PAGE  # noqa: E402


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


def test_check_relative_and_inline_resources_pass():
    page = GOOD_PAGE + '<script src="./x.js"></script><link rel="stylesheet" href="x.css">'
    fails, _ = artifactctl.check_html(page, size=1024)
    assert fails == []


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


def test_prepare_creates_dir_and_excludes_it(run, repo):
    r = run("prepare", cwd=repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(repo / ".artifacts")
    assert (repo / ".artifacts").is_dir()
    assert ".artifacts/\n" in (repo / ".git" / "info" / "exclude").read_text()
    # idempotent
    run("prepare", cwd=repo)
    assert (repo / ".git" / "info" / "exclude").read_text().count(".artifacts/\n") == 1
    assert git("status", "--porcelain", cwd=repo) == ""


def test_prepare_excludes_in_worktree(run, repo, tmp_path):
    wt = tmp_path / "wt"
    git("worktree", "add", "-q", "-b", "feat", str(wt), cwd=repo)
    r = run("prepare", cwd=wt)
    assert r.returncode == 0, r.stderr
    assert (wt / ".artifacts").is_dir()
    assert ".artifacts/\n" in (repo / ".git" / "info" / "exclude").read_text()
    assert not (wt / ".git" / "info").exists()  # .git is a file here; nothing was written beside it


def test_prepare_outside_git(run, tmp_path):
    r = run("prepare", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / ".artifacts").is_dir()


def test_prepare_takes_explicit_dir(run, repo):
    sub = repo / "docs"
    sub.mkdir()
    r = run("prepare", str(sub), cwd=repo)
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


@pytest.mark.parametrize("tag", [
    '<script src=https://cdnjs.cloudflare.com/ajax/libs/x/1/x.js></script>',
    '<script src="lib/x.js"></script>',
    '<script src="./x.js"></script>',
])
def test_check_allows_unquoted_allowlisted_and_relative_scripts(tag):
    fails, _ = artifactctl.check_html(GOOD_PAGE + tag, size=1024)
    assert fails == []
