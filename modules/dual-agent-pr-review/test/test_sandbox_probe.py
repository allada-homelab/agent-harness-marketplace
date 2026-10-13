"""Adapter so check.sh's pytest runs the bash suite beside this file (the codex
sandbox probe in scripts/dual_review.sh); the cases live in sandbox_probe.sh."""
import subprocess
from pathlib import Path


def test_sandbox_probe_suite():
    suite = Path(__file__).with_name("sandbox_probe.sh")
    result = subprocess.run(["bash", str(suite)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failed" in result.stdout
