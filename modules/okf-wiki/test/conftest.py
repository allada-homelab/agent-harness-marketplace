import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from okf_testlib import make_repo  # noqa: E402


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repo with one commit, a `.wiki/`, and isolated state/cache dirs."""
    return make_repo(tmp_path, monkeypatch)
