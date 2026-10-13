"""Adapter so check.sh's pytest runs the bash suite beside this file (status and
exit reporting of `dual_review.sh run`); the cases live in run_round.sh."""
import subprocess
from pathlib import Path


def test_run_round_suite():
    suite = Path(__file__).with_name("run_round.sh")
    result = subprocess.run(["bash", str(suite)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failed" in result.stdout
