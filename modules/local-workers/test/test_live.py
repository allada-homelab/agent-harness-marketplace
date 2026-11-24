"""Opt-in checks against the real backends: set LW_LIVE_TESTS=1."""

import os
import subprocess
from pathlib import Path

import pytest

from decision_client import decide_batch, fetch_health

pytestmark = pytest.mark.skipif(not os.environ.get("LW_LIVE_TESTS"), reason="hits the real pi and decision model; set LW_LIVE_TESTS=1")

DECISION_URL = os.environ.get("LW_DECISION_URL", "http://10.69.1.169:8690/upstream/decision-default")
PLUGIN = Path(__file__).resolve().parent.parent

TICKET = ("Ticket 4471: since 09:10 the checkout page returns HTTP 500 for every customer; no orders have gone "
          "through in 40 minutes. Severity guide: P1 = a revenue path fully down; P2 = degraded but working; "
          "P3 = cosmetic.")
PRIORITY = {"type": "choice", "instructions": "Which priority does the severity guide assign?",
            "criteria": {"p1": "Revenue path fully down", "p2": "Degraded but working", "p3": "Cosmetic"}}
UNKNOWABLE = {"type": "noul", "instructions": "The reporter is left-handed."}


def test_real_pi_run_answers_and_resumes(tmp_path):
    env = {**os.environ, "XDG_STATE_HOME": str(tmp_path)}
    run = [str(PLUGIN / "bin" / "pi-run"), "--read-only", "--timeout", "300"]
    first = subprocess.run([*run, "Read README.md in this directory. Reply with only its first heading, verbatim."],
                           cwd=PLUGIN, env=env, capture_output=True, text=True, timeout=330)
    assert first.returncode == 0, first.stderr
    assert "local-workers" in first.stdout
    session = first.stderr.split("pi-run: session ")[1].split()[0]
    again = subprocess.run([*run, "--session", session, "What heading did you just quote? Reply with it only."],
                           cwd=tmp_path, env=env, capture_output=True, text=True, timeout=330)
    assert again.returncode == 0, again.stderr
    assert "local-workers" in again.stdout


def test_real_health_reports_the_floor():
    assert fetch_health(DECISION_URL)["noul_floor"] == pytest.approx(0.801)


def test_real_decision_batch_answers_and_flags_the_coin_flip():
    out = decide_batch(DECISION_URL, [{"id": "ticket", "state": TICKET, "questions": {"priority": PRIORITY}},
                                      {"id": "unknowable", "state": TICKET, "questions": {"lefty": UNKNOWABLE}}])
    assert out["summary"]["ok"] == 2, out
    by_id = {r["id"]: r for r in out["results"]}
    assert by_id["ticket"]["answers"]["priority"]["choice"] == "p1"
    assert by_id["unknowable"]["answers"]["lefty"].get("floored") is True
