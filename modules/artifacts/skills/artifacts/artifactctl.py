#!/usr/bin/env python3
"""artifactctl — the local artifacts helper: prepare | check | open.

Stdlib only. Exit codes: 0 ok, 1 check failures, 2 usage or missing file.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SIZE_CAP = 16 * 1024 * 1024
SCRIPT_HOSTS = {"cdnjs.cloudflare.com", "cdn.jsdelivr.net", "unpkg.com", "cdn.tailwindcss.com", "code.jquery.com"}
STYLE_HOST = "fonts.googleapis.com"
FORBIDDEN = ("window.claude", "claude.ai", "claude.use(", "ArtifactData")

_DOCTYPE = re.compile(r"<!doctype\s+html", re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_VIEWPORT = re.compile(r"<meta\s[^>]*name\s*=\s*[\"']viewport[\"']", re.I)
_ROOT = re.compile(r":root\s*\{")
_DARK = re.compile(r"prefers-color-scheme\s*:\s*dark|\[data-theme\s*=\s*[\"']dark[\"']\]", re.I)
_SCRIPT_SRC = re.compile(r"<script\s[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
_LINK = re.compile(r"<link\s[^>]*>", re.I)
_ATTR = re.compile(r"\b(rel|href)\s*=\s*[\"']([^\"']*)[\"']", re.I)
_URL = re.compile(r"^(?:https?:)?//([^/]+)(/.*)?$", re.I)


def _host(url: str) -> tuple[str, str] | None:
    m = _URL.match(url.strip())
    return (m.group(1).lower(), m.group(2) or "/") if m else None


def check_html(text: str, size: int) -> tuple[list[str], list[str]]:
    """Static gate for one page. Returns (failures, warnings); one line per finding."""
    text = text.lstrip("﻿")
    fails: list[str] = []
    warns: list[str] = []
    if not _DOCTYPE.search(text):
        fails.append("doctype: missing <!doctype html>; the page is a standalone file, nothing wraps it")
    m = _TITLE.search(text)
    title = " ".join(m.group(1).split()) if m else ""
    if not title:
        fails.append("title: missing <title>; name the page in two to four words")
    elif len(title) > 60:
        fails.append(f"title: {len(title)} chars; a name, not a summary (max 60)")
    if not _VIEWPORT.search(text):
        fails.append("viewport: missing <meta name=\"viewport\">; the page must work at phone width")
    if not _ROOT.search(text):
        fails.append("tokens: no :root { } block; every color is a token defined there first")
    elif not _DARK.search(text):
        warns.append("theme: no dark-mode rule; fine only for a deliberately single-theme design")
    for needle in FORBIDDEN:
        if needle in text:
            fails.append(f"forbidden: {needle!r} is hosted-only; see references/runtime-seam.md")
            break
    for src in _SCRIPT_SRC.findall(text):
        h = _host(src)
        if h is None:
            continue  # relative or inline: ships with the page
        host, path = h
        ok = host in SCRIPT_HOSTS and (host != "cdn.jsdelivr.net" or path.startswith("/npm/"))
        if not ok:
            fails.append(f"host: script from {src} is not on the CDN allowlist")
    for tag in _LINK.findall(text):
        attrs = {k.lower(): v for k, v in _ATTR.findall(tag)}
        if "stylesheet" not in attrs.get("rel", "").lower().split():
            continue
        h = _host(attrs.get("href", ""))
        if h is not None and h[0] != STYLE_HOST:
            fails.append(f"host: stylesheet from {attrs['href']} is not {STYLE_HOST}")
    if size > SIZE_CAP:
        fails.append(f"size: {size} bytes exceeds the 16 MB cap")
    return fails, warns


def exclude_path(directory: Path) -> Path | None:
    """The git exclude file that governs `directory`, or None outside a repo.
    `--git-path` resolves to the COMMON dir, so a linked worktree shares main's info/exclude."""
    try:
        out = subprocess.run(["git", "-C", str(directory), "rev-parse", "--git-path", "info/exclude"],
                             check=True, text=True, capture_output=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    p = Path(out)
    return p if p.is_absolute() else (directory / p).resolve()


def prepare(directory: Path) -> Path:
    out = (directory / ".artifacts").resolve()
    out.mkdir(parents=True, exist_ok=True)
    exclude = exclude_path(directory)
    if exclude is not None:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude.read_text() if exclude.exists() else ""
        if ".artifacts/" not in existing.splitlines():
            with exclude.open("a") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(".artifacts/\n")
    return out


def is_display_available(env: dict, platform: str) -> bool:
    return platform == "darwin" or bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def open_file(path: Path) -> None:
    platform = os.environ.get("ARTIFACTCTL_PLATFORM", sys.platform)
    print(path)
    if not is_display_available(os.environ, platform):
        return
    opener = "open" if platform == "darwin" else "xdg-open"
    if shutil.which(opener) is None:
        return
    try:  # both openers hand off and return at once; the timeout only guards a stuck desktop
        subprocess.run([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _file_arg(arg: str | None) -> Path:
    if not arg:
        print("artifactctl: a file path is required", file=sys.stderr)
        raise SystemExit(2)
    p = Path(arg).expanduser().resolve()
    if not p.is_file():
        print(f"artifactctl: {p} is not a file", file=sys.stderr)
        raise SystemExit(2)
    return p


def main(argv: list[str]) -> int:
    if len(argv) < 1 or argv[0] not in ("prepare", "check", "open"):
        print("usage: artifactctl.py prepare [DIR] | check FILE | open FILE", file=sys.stderr)
        return 2
    verb, rest = argv[0], argv[1:]
    if verb == "prepare":
        print(prepare(Path(rest[0]).expanduser() if rest else Path.cwd()))
        return 0
    path = _file_arg(rest[0] if rest else None)
    if verb == "open":
        open_file(path)
        return 0
    fails, warns = check_html(path.read_text(errors="replace"), path.stat().st_size)
    for w in warns:
        print(f"WARN {w}")
    for f in fails:
        print(f"FAIL {f}")
    if fails:
        return 1
    print(f"ok {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
