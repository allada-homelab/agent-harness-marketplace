"""bin/lint-workflows.py: `meta` must be readable as data, without a JS engine.

The pi and dsh `run_workflow` bridges build their catalog from `meta` without
running the file, so anything that needs evaluation is a contract break. See
workflow-contract/README.md.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINT = ROOT / "bin" / "lint-workflows.py"

GOOD = """// a workflow
export const meta = {
  name: 'ship-it',
  description: "Do the thing, then check it didn't break anything.",
  phases: [
    { title: 'Plan' },
    { title: 'Do' },
  ],
}

const out = await agent(`Do ${args.task}`, { label: 'do', phase: 'Do', model: 'sonnet', agentType: 'm:worker' })
return { out }
"""


def lint(tmp_path, source, filename="ship-it.workflow.js"):
    d = tmp_path / "mod" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(source)
    return subprocess.run([sys.executable, str(LINT), str(tmp_path / "mod")],
                          capture_output=True, text=True)


def test_literal_meta_passes(tmp_path):
    p = lint(tmp_path, GOOD)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "FAIL" not in p.stdout and "WARN" not in p.stdout


def test_missing_meta_fails(tmp_path):
    p = lint(tmp_path, "return { ok: true }\n")
    assert p.returncode == 1 and "export const meta" in p.stdout


def test_computed_meta_fails(tmp_path):
    p = lint(tmp_path, GOOD.replace("name: 'ship-it'", "name: NAME"))
    assert p.returncode == 1 and "not a pure object literal" in p.stdout


def test_template_string_in_meta_fails(tmp_path):
    p = lint(tmp_path, GOOD.replace("name: 'ship-it'", "name: `ship-${x}`"))
    assert p.returncode == 1 and "not a pure object literal" in p.stdout


def test_spread_in_meta_fails(tmp_path):
    p = lint(tmp_path, GOOD.replace("phases: [", "...BASE,\n  phases: ["))
    assert p.returncode == 1 and "not a pure object literal" in p.stdout


def test_non_kebab_name_fails(tmp_path):
    p = lint(tmp_path, GOOD.replace("name: 'ship-it'", "name: 'Ship It'"))
    assert p.returncode == 1 and "meta.name" in p.stdout


def test_missing_description_fails(tmp_path):
    p = lint(tmp_path, GOOD.replace('description: "Do the thing, then check it didn\'t break anything."', "description: ''"))
    assert p.returncode == 1 and "meta.description" in p.stdout


def test_malformed_phases_fail(tmp_path):
    p = lint(tmp_path, GOOD.replace("{ title: 'Plan' }", "'Plan'"))
    assert p.returncode == 1 and "meta.phases" in p.stdout


def test_off_contract_agent_option_warns_only(tmp_path):
    p = lint(tmp_path, GOOD.replace("model: 'sonnet'", "temperature: 0.4"))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "WARN" in p.stdout and "temperature" in p.stdout


def test_non_kebab_filename_fails(tmp_path):
    p = lint(tmp_path, GOOD, filename="Ship_It.workflow.js")
    assert p.returncode == 1 and "dispatch id" in p.stdout
