"""The bash suite beside this file holds the real cases (extracted-function
tests of run_with_timeout in scripts/dual_review.sh, including the no-`timeout`
macOS branch). check.sh runs pytest, so this is the adapter that gives it a seat
in the gate; it moved here from the harness layer when the tree copy retired."""
import subprocess
from pathlib import Path


def test_timeout_portability_suite():
    suite = Path(__file__).with_name("timeout_portability.sh")
    result = subprocess.run(["bash", str(suite)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 failed" in result.stdout
