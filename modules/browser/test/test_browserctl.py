import json
import stat


def test_doctor_ok_json(sandbox, run):
    r = run(sandbox, "doctor", "--json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["ok"] is True
    assert d["agentBrowser"] == "0.37.1"
    assert d["chrome"].endswith("chrome-linux64/chrome")


def test_doctor_reports_missing_chrome(sandbox, run):
    home, _, chrome = sandbox
    (home / ".browserctl" / "chrome" / "current").unlink()
    r = run(sandbox, "doctor", "--json")
    assert r.returncode == 2
    d = json.loads(r.stdout)
    assert d["ok"] is False
    assert any("chrome" in p.lower() for p in d["problems"])


def test_run_auto_composes_flags_and_creates_profile(sandbox, run, argv):
    home, _, chrome = sandbox
    r = run(sandbox, "run", "--identity", "work", "--session", "s1", "--", "open", "https://example.com")
    assert r.returncode == 0, r.stderr
    a = argv(sandbox)
    profile = home / ".browserctl" / "profiles" / "work"
    assert a == [
        "--session", "s1",
        "--profile", str(profile),
        "--executable-path", str(chrome),
        "--pin-tab",
        "--idle-timeout", "30m",
        "open", "https://example.com",
    ]
    assert profile.is_dir()
    assert stat.S_IMODE(profile.stat().st_mode) == 0o700


def test_run_hybrid_is_headed_without_idle_timeout(sandbox, run, argv):
    r = run(sandbox, "run", "--identity", "work", "--mode", "hybrid", "--session", "s1", "--", "open", "https://example.com")
    assert r.returncode == 0, r.stderr
    a = argv(sandbox)
    assert "--headed" in a
    assert "--idle-timeout" not in a


def test_run_default_session_is_identity_plus_cwd_hash(sandbox, tmp_path, run, argv):
    cwd = tmp_path / "proj"
    cwd.mkdir()
    r = run(sandbox, "run", "--identity", "work", "--", "get", "url", cwd=cwd)
    assert r.returncode == 0, r.stderr
    a = argv(sandbox)
    sess = a[a.index("--session") + 1]
    assert sess.startswith("work-") and len(sess) == len("work-") + 8


def test_run_passes_exit_code_through(sandbox, run):
    r = run(sandbox, "run", "--identity", "work", "--session", "s1", "--", "click", "@e9", env={"FAKE_AB_EXIT": "1"})
    assert r.returncode == 1


def test_run_refuses_without_chrome(sandbox, run):
    home, _, _ = sandbox
    (home / ".browserctl" / "chrome" / "current").unlink()
    r = run(sandbox, "run", "--identity", "work", "--session", "s1", "--", "get", "url")
    assert r.returncode == 2
    assert "doctor" in r.stderr


def test_run_rejects_bad_identity(sandbox, run):
    r = run(sandbox, "run", "--identity", "../evil", "--", "get", "url")
    assert r.returncode == 2


def test_identities_lists_profiles(sandbox, run):
    home, _, _ = sandbox
    for n in ("work", "scratch"):
        (home / ".browserctl" / "profiles" / n).mkdir(parents=True)
    r = run(sandbox, "identities")
    assert r.stdout.split() == ["scratch", "work"]


def test_export_wraps_state_save(sandbox, run, argv):
    r = run(sandbox, "export", "--identity", "work", "--session", "s1", "--out", "auth.json")
    assert r.returncode == 0, r.stderr
    a = argv(sandbox)
    assert a[-3:] == ["state", "save", "auth.json"]


def test_close_wraps_close(sandbox, run, argv):
    r = run(sandbox, "close", "--identity", "work", "--session", "s1")
    assert r.returncode == 0, r.stderr
    assert argv(sandbox)[-1] == "close"


def test_chrome_env_override_wins(sandbox, tmp_path, run, argv):
    alt = tmp_path / "alt-chrome"
    alt.write_text("#!/bin/sh\n")
    alt.chmod(0o755)
    r = run(sandbox, "run", "--identity", "work", "--session", "s1", "--", "get", "url", env={"BROWSERCTL_CHROME": str(alt)})
    assert r.returncode == 0, r.stderr
    a = argv(sandbox)
    assert a[a.index("--executable-path") + 1] == str(alt)
