"""Adapter so check.sh's pytest runs the bash suite beside this file (the
dual_review.sh helpers behind prepare --since, the codex evidence gate, failure
causes and inline anchors); the cases live in helpers.sh."""
import subprocess
from pathlib import Path


def test_helpers_suite():
    suite = Path(__file__).with_name("helpers.sh")
    result = subprocess.run(["bash", str(suite)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failed" in result.stdout
