"""End-to-end tests: drive bin/switchboard as hooks and the CLI do, against a temp state dir."""

import importlib.util
import json
from importlib.machinery import SourceFileLoader
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parent.parent / "bin" / "switchboard"

# A stand-in adapter: its resource lives in any directory holding a .demo-root file.
DEMO_ADAPTER = """
import os
RESOURCE = "demo-stack"
def applies(cwd): return os.path.exists(os.path.join(cwd, ".demo-root"))
def probe(): return {"running": False, "summary": "stopped", "served_from": [], "facts": {}}
def classify(command): return {"make up": "starts or stops", "make migrate": "migrates"}.get(command.strip())
def shared_writes(command): return ["demo-db"] if "psql demo -c 'UPDATE" in command else []
"""


def dead_pid() -> int:
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


class Switchboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.cwd = self.home / "work"
        self.cwd.mkdir()
        (self.home / "state" / "adapters").mkdir(parents=True)
        (self.home / "state" / "adapters" / "demo.py").write_text(DEMO_ADAPTER)
        # Each session is its own live process, as each Claude Code session is.
        self.procs = {s: subprocess.Popen(["sleep", "600"]) for s in "ABC"}
        self.pids = {s: p.pid for s, p in self.procs.items()}

    def tearDown(self):
        for proc in self.procs.values():
            proc.kill()
            proc.wait()
        self.tmp.cleanup()

    def env(self, who, adapters="none", harness="claude", hook=False, inside=None):
        """The env a session's hooks (`hook`) or shell commands get on `harness`; `inside` names the
        Claude session it was launched from, whose variables it inherits."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "SWITCHBOARD", "PI_", "DSH_"))}
        env.update(
            SWITCHBOARD_HOME=str(self.home / "state"),
            SWITCHBOARD_CLAUDE_SESSIONS=str(self.home / "no-registry"),
            SWITCHBOARD_ADAPTERS=adapters,
        )
        if inside:
            env.update(CLAUDE_CODE_SESSION_ID=f"sid-{inside}", CLAUDE_PID=str(self.pids[inside[0]]))
        if who and harness == "claude":
            env.update(CLAUDE_CODE_SESSION_ID=f"sid-{who}", CLAUDE_PID=str(self.pids[who[0]]))
        elif who and harness == "pi":  # the pi hook-runner adds PI_PID; pi's bash tool does not
            env.update(PI_SESSION_ID=f"sid-{who}", **({"PI_PID": str(self.pids[who[0]])} if hook else {}))
        elif who:
            env.update(DSH_SESSION_ID=f"sid-{who}")
        return env

    def cli(self, who, *args, ok=True, adapters="none", harness="claude"):
        out = subprocess.run([sys.executable, str(BIN), *args], capture_output=True, text=True,
                             env=self.env(who, adapters, harness), cwd=self.cwd)
        if ok is not None:
            self.assertEqual(out.returncode == 0, ok, f"{args}: rc={out.returncode}\n{out.stdout}{out.stderr}")
        return out

    def hook(self, who, event, adapters="none", harness="claude", inside=None, **payload):
        data = {"session_id": f"sid-{who}", "cwd": str(self.cwd), **payload}
        env = self.env(who, adapters, harness, hook=True, inside=inside)
        out = subprocess.run([sys.executable, str(BIN), "hook", event], input=json.dumps(data),
                             capture_output=True, text=True, env=env, cwd=self.cwd)
        self.assertEqual(out.returncode, 0, out.stderr)
        if not out.stdout.strip():
            return ""
        result = json.loads(out.stdout)
        if event == "stop":
            self.assertEqual(result["decision"], "block")
            return result["reason"]
        return result["hookSpecificOutput"]["additionalContext"]

    def db(self):
        return sqlite3.connect(self.home / "state" / "switchboard.db")

    def test_direct_messages_replies_and_stop_delivery(self):
        for s in "AB":
            self.hook(s, "session-start")
        b_name = self.cli("B", "whoami").stdout.split()[0]
        out = self.cli("A", "post", "can you rebase onto dev?", "--to", b_name).stdout
        pid = int(out.split("#")[1].split()[0])
        self.assertIn("sees this after its current tool call, or before it goes idle", out)
        self.cli("A", "post", "dev is green again")
        stopped = self.hook("B", "stop")  # the turn ends with a direct post unread: it continues
        self.assertIn(f"→ you #{pid}: can you rebase onto dev?", stopped)
        self.assertIn("dev is green again", stopped)
        self.assertEqual(self.hook("B", "stop"), "", "a continued turn's stop does not block again")
        self.cli("A", "post", "broadcast only")
        self.assertEqual(self.hook("B", "stop"), "", "broadcasts wait for the next prompt")
        self.cli("B", "reply", str(pid), "rebased, pushed")
        self.assertEqual(self.hook("A", "stop", stop_hook_active=True), "", "a continued turn doesn't block on replies alone")
        self.assertIn(f"(re #{pid}): [reply] rebased, pushed", self.hook("A", "stop"))
        self.assertIn("--wait needs --to", self.cli("A", "post", "x", "--wait", "1", ok=False).stderr)
        waiting = subprocess.Popen([sys.executable, str(BIN), "post", "ready to merge?", "--to", b_name, "--wait", "1"],
                                   stdout=subprocess.PIPE, text=True, env=self.env("A"), cwd=self.cwd)
        deadline = time.time() + 20
        while time.time() < deadline:
            with self.db() as db:
                asked = db.execute("SELECT id FROM posts WHERE body = 'ready to merge?'").fetchone()
            if asked:
                break
            time.sleep(0.2)
        self.cli("B", "reply", str(asked[0]), "yes, merge")
        out, _ = waiting.communicate(timeout=30)
        self.assertEqual(waiting.returncode, 0, out)
        self.assertIn("yes, merge", out)
        self.cli("A", "lease", "box", "acquire")
        self.cli("B", "lease", "box", "kick", "--note", "user asked")
        self.assertIn(f"you no longer hold box: {b_name} kicked you (user asked)", self.hook("A", "prompt", prompt="?"))

    def test_registry_and_digest(self):
        self.hook("A", "session-start", source="startup")
        self.cli("A", "doing", "fixing", "AI-1")
        digest = self.hook("B", "session-start", source="startup")
        self.assertIn("1 other active session", digest)
        self.assertIn("fixing AI-1", digest)
        who = self.cli("B", "who").stdout
        self.assertIn("work-sid-", who)
        self.assertIn("(you)", who)
        self.assertEqual((self.home / "state").stat().st_mode & 0o777, 0o700, "the state dir holds prompts")

    def test_feed_delivery_once_and_directed(self):
        for s in "ABC":
            self.hook(s, "session-start")
        b_name = self.cli("B", "whoami").stdout.split()[0]
        self.cli("A", "post", "dev", "is", "broken", "--topic", "heads-up")
        self.cli("A", "post", "only for B", "--to", b_name)
        got = self.hook("B", "prompt", prompt="hi")
        self.assertIn("2 new post", got)
        self.assertIn("[heads-up] dev is broken", got)
        self.assertIn("only for B", got)
        self.assertEqual(self.hook("B", "post-tool", tool_name="Read", tool_input={}), "")
        c_got = self.hook("C", "post-tool", tool_name="Read", tool_input={})
        self.assertIn("dev is broken", c_got)
        self.assertNotIn("only for B", c_got)
        self.assertEqual(self.hook("A", "prompt", prompt="x"), "")

    def test_lease_queue_handoff(self):
        for s in "ABC":
            self.hook(s, "session-start")
        self.cli("A", "lease", "box", "join", "--est", "30", "--purpose", "e2e")
        self.assertIn("acquired box for 60m", self.cli("A", "lease", "box", "acquire").stdout)
        self.cli("B", "lease", "box", "join", "--est", "20", "--purpose", "evals")
        self.cli("C", "lease", "box", "join", "--est", "10", "--purpose", "smoke")
        self.assertIn("held by", self.cli("B", "lease", "box", "acquire", ok=False).stdout)
        status = self.cli("C", "lease", "box", "status").stdout
        self.assertIn("1. work-sid-", status)
        self.assertIn("(you)", status)
        self.cli("B", "lease", "box", "wait", "--timeout", "0", ok=False)
        self.cli("A", "lease", "box", "release", "--result", "pass: e2e green")
        self.assertIn("first in the queue", self.cli("C", "lease", "box", "acquire", ok=False).stdout)
        nudge = self.hook("B", "prompt", prompt="?")
        self.assertIn("released box: pass: e2e green", nudge)
        self.assertIn("box is free and you are first in the queue", nudge)
        self.assertIn("acquired box", self.cli("B", "lease", "box", "wait", "--timeout", "1").stdout)
        # --note and --summary are what agents reach for; both record the result.
        self.cli("B", "lease", "box", "release", "--note", "fail: evals red")
        self.assertIn("acquired box", self.cli("C", "lease", "box", "acquire").stdout)
        self.cli("C", "lease", "box", "release", "--summary", "aborted: smoke skipped")
        ledger = self.cli("C", "ledger", "ls", "--resource", "box").stdout
        self.assertIn("release: [box] pass: e2e green", ledger)
        self.assertIn("release: [box] fail: evals red", ledger)
        self.assertIn("release: [box] aborted: smoke skipped", ledger)

    def test_durations_aliases_and_full_posts(self):
        self.hook("A", "session-start")
        self.hook("B", "session-start")
        out = self.cli("A", "lease", "box", "acquire", "--ttl", "2h").stdout
        self.assertIn("acquired box for 120m", out)
        self.assertIn("renew --ttl 2h", out)
        self.cli("A", "lease", "box", "renew", "--minutes", "1h30m")
        with self.db() as db:
            left = db.execute("SELECT expires FROM leases").fetchone()[0] - time.time()
        self.assertAlmostEqual(left / 60, 90, delta=1)
        self.assertIn("not a duration", self.cli("A", "lease", "box", "renew", "--ttl", "soon", ok=False).stderr)
        self.cli("B", "lease", "box", "join", "--est", "45m", "--purpose", "evals")
        self.cli("B", "lease", "box", "kick", "--reason", "user said so")
        self.cli("A", "post", "x" * 500)
        got = self.hook("B", "prompt", prompt="?")
        post_id = int(got.split("feed --id ")[1].split("`")[0])
        self.assertIn("x" * 500, self.cli("B", "feed", "--id", str(post_id)).stdout)

    def test_shared_db_writes_are_ledgered_and_flagged_at_release(self):
        self.hook("A", "session-start")
        self.cli("A", "lease", "box", "acquire")
        write = "psql demo -c 'UPDATE users SET has_access=1 WHERE id=2'"
        got = self.hook("A", "post-tool", adapters="demo", tool_name="Bash", tool_input={"command": write})
        self.assertIn("wrote to the shared demo-db", got)
        read = "psql demo -c 'select count(*) from users'"
        self.assertEqual(self.hook("A", "post-tool", adapters="demo", tool_name="Bash", tool_input={"command": read}), "")
        out = self.cli("A", "lease", "box", "release", "--result", "pass").stdout
        self.assertIn("warning: 1 write(s) to demo-db with no ledger entry", out)
        self.assertIn("write: [demo-db] psql demo", self.cli("A", "ledger", "ls").stdout)
        self.cli("A", "lease", "box", "acquire")
        self.hook("A", "post-tool", adapters="demo", tool_name="Bash", tool_input={"command": write})
        self.cli("A", "ledger", "add", "granted user 2 access", "--resource", "demo-db", "--rollback", "set it to 0")
        self.assertNotIn("warning", self.cli("A", "lease", "box", "release", "--result", "pass").stdout)

    def test_lease_posts_skip_sessions_outside_the_resource(self):
        self.hook("A", "session-start")
        self.hook("B", "session-start")
        self.cli("A", "lease", "demo-stack", "acquire", "--purpose", "e2e")
        self.cli("A", "post", "dev is broken")
        got = self.hook("B", "prompt", adapters="demo", prompt="?")  # B's cwd holds no .demo-root
        self.assertIn("dev is broken", got)
        self.assertNotIn("acquired demo-stack", got)

    def repo(self, name, branch):
        path = self.home / name
        path.mkdir()
        git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q", "-b", branch], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        return path

    def test_overview_history_and_find(self):
        wt = self.repo("wt", "fix/ai-3217-reads")
        other = self.repo("other", "feat/docs")
        self.hook("A", "session-start", transcript_path="/t/A.jsonl")
        self.hook("B", "session-start")
        a_name = self.cli("A", "whoami").stdout.split()[0]
        self.hook("A", "prompt", cwd=str(wt), prompt="fix AI-3217, see https://github.com/o/r/pull/44083")
        self.hook("A", "post-tool", tool_name="Edit", tool_input={"file_path": str(other / "README.md")})
        self.hook("A", "post-tool", tool_name="Bash", tool_input={"command": "gh pr create --fill"},
                  tool_response={"stdout": "https://github.com/o/r/pull/9\n", "stderr": ""})
        self.assertIn(f"{a_name}: [pr] opened https://github.com/o/r/pull/9", self.hook("B", "prompt", prompt="?"))
        who = self.cli("B", "who").stdout
        self.assertIn("last ask: fix AI-3217", who)
        self.assertIn("https://github.com/o/r/pull/9", who)
        self.cli("A", "doing", "AI-3217: stream reads")
        self.assertIn("doing: AI-3217: stream reads", self.cli("B", "who").stdout)
        self.cli("B", "todo", "add", "rebase", "it", "--owner", a_name)
        self.assertIn(f"rebase it @{a_name}", self.cli("B", "todo", "ls").stdout)
        self.procs["A"].kill()
        self.procs["A"].wait()
        self.cli("B", "todo", "add", "x", "--owner", a_name, ok=False)  # only live sessions take work
        found = self.cli("B", "find", "AI-3217").stdout
        self.assertIn(f"{a_name} (ended", found)
        self.assertIn(a_name, self.cli("B", "find", "feat/docs").stdout)
        self.assertIn("no session touched", self.cli("B", "find", "AI-9999").stdout)
        shown = self.cli("B", "show", a_name).stdout
        for want in ("ended", "transcript: /t/A.jsonl", "branch: wt@fix/ai-3217-reads", "worktree: " + str(other.resolve()),
                     "pr: https://github.com/o/r/pull/44083", "ticket: AI-3217", "[pr] opened"):
            self.assertIn(want, shown)
        self.assertNotIn("prompt: fix", shown)
        self.assertIn("prompt: fix AI-3217", self.cli("B", "show", a_name, "--prompts").stdout)
        self.assertIn(a_name, self.cli("B", "show", "sid-A").stdout)  # by id prefix
        self.assertIn("doing: AI-3217: stream reads", shown)  # a status change is history too

    def test_status_nudges_and_quiet_sessions(self):
        self.hook("A", "session-start")
        self.hook("B", "session-start")
        self.assertNotIn("your status", self.hook("A", "prompt", prompt="hi"))  # too new to nag
        with self.db() as db:
            db.execute("UPDATE sessions SET started_at = started_at - 1200")
        self.assertIn("your status is not set", self.hook("A", "prompt", prompt="go"))
        self.assertNotIn("your status", self.hook("A", "prompt", prompt="again"))  # hourly at most
        self.cli("A", "doing", "AI-1: thing")
        with self.db() as db:
            db.execute("UPDATE sessions SET nudged_at = NULL")
            db.execute("UPDATE activity SET ts = ts - 60 WHERE kind = 'doing'")
        self.assertNotIn("your status", self.hook("A", "prompt", prompt="more"))
        self.assertIn("still says 'AI-1: thing'", self.hook("A", "prompt", prompt="now AI-22 please"))
        self.cli("B", "lease", "box", "acquire", "--purpose", "e2e for PR 7")
        self.assertIn("doing: e2e for PR 7", self.cli("A", "who").stdout)
        with self.db() as db:
            db.execute("UPDATE sessions SET last_seen = last_seen - 30000 WHERE id = 'sid-A'")
        self.cli("B", "lease", "box", "release", "--result", "pass")
        out = self.cli("B", "who").stdout
        self.assertIn("+1 quiet for over 6h", out)
        self.assertIn("AI-1: thing", self.cli("B", "who", "--all").stdout)

    def test_dead_or_expired_holder_is_taken_over(self):
        self.pids["C"] = dead_pid()
        for s in "ABC":
            self.hook(s, "session-start")
        self.cli("C", "lease", "box", "acquire")
        self.assertIn("took over from", self.cli("A", "lease", "box", "acquire").stdout)
        with self.db() as db:
            db.execute("UPDATE leases SET expires = ?", (time.time() - 1,))
        self.assertIn("took over from", self.cli("B", "lease", "box", "acquire").stdout)
        with self.db() as db:
            db.execute("UPDATE leases SET expires = ?", (time.time() - 1,))
        self.assertIn("your box lease expired", self.hook("B", "prompt", prompt="?"))

    def test_clear_replaces_the_session_and_releases_its_leases(self):
        self.hook("A", "session-start")
        self.hook("B", "session-start")
        self.cli("A", "lease", "box", "acquire", "--purpose", "proof")
        self.hook("A", "session-start", source="resume")  # the same session again ends nothing
        self.assertIn("held by", self.cli("B", "lease", "box", "status").stdout)
        self.hook("A2", "session-start", source="clear")  # a new session in A's process
        self.assertIn("holder session was replaced", self.hook("B", "prompt", prompt="?"))
        self.assertIn("box: free", self.cli("B", "lease", "box", "status").stdout)
        with self.db() as db:
            self.assertEqual(db.execute("SELECT end_reason FROM sessions WHERE id = 'sid-A'").fetchone()[0], "replaced")

    def test_todo_board(self):
        self.hook("A", "session-start")
        self.hook("B", "session-start")
        self.cli("A", "todo", "add", "port", "the", "eval", "--project", "albus", "--take")
        self.cli("A", "todo", "add", "write", "docs")
        self.assertIn("is owned by", self.cli("B", "todo", "take", "1", ok=False).stderr)
        self.cli("B", "todo", "take", "2")
        self.cli("B", "todo", "done", "2", "--note", "merged")
        board = self.cli("A", "todo", "ls").stdout
        self.assertIn("[doing] albus: port the eval", board)
        self.assertNotIn("write docs", board)
        self.assertIn("todo #2 done: write docs — merged", self.hook("A", "prompt", prompt="?"))

    def test_ledger_rollback(self):
        self.hook("A", "session-start")
        self.cli("A", "ledger", "add", "set has_access=1 for user 10", "--rollback", "set it back to 0", "--resource", "demo-db")
        out = self.cli("A", "ledger", "ls").stdout
        self.assertIn("[demo-db] set has_access=1", out)
        self.assertIn("rollback: set it back to 0", out)

    def pre_tool(self, who, command, cwd, **payload):
        data = {"session_id": f"sid-{who}", "cwd": str(cwd), "tool_name": "Bash", "tool_input": {"command": command}, **payload}
        out = subprocess.run([sys.executable, str(BIN), "hook", "pre-tool"], input=json.dumps(data),
                             capture_output=True, text=True, env=self.env(who, "demo"), cwd=self.cwd)
        self.assertEqual(out.returncode, 0, out.stderr)
        if not out.stdout.strip():
            return "allow"
        return json.loads(out.stdout)["hookSpecificOutput"].get("permissionDecision", "allow")  # allow + a warning

    def test_stack_commands_need_the_lease(self):
        demo = self.cwd / "demo"
        demo.mkdir()
        (demo / ".demo-root").touch()
        self.hook("A", "session-start")
        self.hook("B", "session-start")
        start = "make up"
        self.assertEqual(self.pre_tool("A", start, demo), "deny")
        self.assertIn("deny: [demo-stack] starts or stops: make up", self.cli("A", "ledger", "ls").stdout)
        self.assertEqual(self.pre_tool("A", "git status", demo), "allow")
        self.assertEqual(self.pre_tool("A", start, self.cwd), "allow")  # the resource doesn't live here
        self.cli("A", "lease", "demo-stack", "acquire", "--purpose", "e2e")
        self.assertIn("demo-stack: held by", self.cli("A", "stack", "status", adapters="demo").stdout)
        self.assertEqual(self.pre_tool("A", start, demo), "allow")
        self.assertEqual(self.pre_tool("B", "make migrate", demo), "deny")
        with self.db() as db:
            db.execute("UPDATE leases SET expires = ?", (time.time() + 60,))
        self.hook("A", "post-tool", tool_name="Bash", tool_input={"command": "ls"})
        with self.db() as db:
            expires = db.execute("SELECT expires FROM leases").fetchone()[0]
        self.assertGreater(expires, time.time() + 50 * 60, "a holder's tool call renews the lease")
        with self.db() as db:
            db.execute("UPDATE leases SET expires = ?", (time.time() - 1,))
        self.hook("A", "post-tool", tool_name="Bash", tool_input={"command": "ls"})
        self.assertEqual(self.pre_tool("A", start, demo), "deny", "an expired lease is not revived")

    # ------------------------------------------------------------ pi and dsh

    def test_pi_and_dsh_hooks_and_cli_name_the_same_session(self):
        self.hook("B", "session-start", harness="pi")
        self.hook("C", "session-start", harness="dsh")
        self.assertIn(f"session=sid-B  pid={self.pids['B']}", self.cli("B", "whoami", harness="pi").stdout)
        self.assertIn("session=sid-C  pid=-", self.cli("C", "whoami", harness="dsh").stdout)
        with self.db() as db:
            rows = db.execute("SELECT id, harness FROM sessions ORDER BY id").fetchall()
        self.assertEqual(rows, [("sid-B", "pi"), ("sid-C", "dsh")])

    def test_pi_session_names_come_from_the_id_tail(self):
        # pi ids are UUIDv7, so their first chars repeat; "sid-B"/"sid-B2" share theirs too.
        self.hook("B", "session-start", harness="pi")
        with self.db() as db:
            name = db.execute("SELECT name FROM sessions WHERE id = 'sid-B'").fetchone()[0]
        self.assertTrue(name.endswith("-id-B"), name)

    def test_a_dsh_subagent_gets_no_session_row(self):
        self.hook("C", "session-start", harness="dsh", agent_id="sid-C")
        self.hook("C", "post-tool", harness="dsh", agent_id="sid-C", tool_name="Bash", tool_input={"command": "ls"})
        with self.db() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sessions WHERE id = 'sid-C'").fetchone())

    def test_a_claude_subagent_is_still_gated_as_its_parent(self):
        demo = self.cwd / "demo"
        demo.mkdir()
        (demo / ".demo-root").touch()
        self.hook("A", "session-start")
        self.assertEqual(self.pre_tool("A", "make up", demo, agent_id="sub-1"), "deny")

    def test_pi_and_dsh_sessions_ignore_the_pid_of_a_claude_they_run_under(self):
        self.hook("A", "session-start")
        self.cli("A", "lease", "box", "acquire", "--purpose", "proof")
        self.hook("B", "session-start", harness="pi", inside="A")
        self.hook("C", "session-start", harness="dsh", inside="A")
        self.assertIn("box: held by", self.cli("A", "lease", "box", "status").stdout)
        with self.db() as db:
            pids = dict(db.execute("SELECT id, pid FROM sessions").fetchall())
        self.assertEqual(pids, {"sid-A": self.pids["A"], "sid-B": self.pids["B"], "sid-C": None})

    def test_a_new_pi_session_replaces_the_last_one_in_its_process(self):
        self.hook("B", "session-start", harness="pi")
        self.cli("B", "lease", "box", "acquire", "--purpose", "proof", harness="pi")
        self.hook("B2", "session-start", harness="pi")  # /new in the same pi process
        self.assertIn("box: free", self.cli("A", "lease", "box", "status").stdout)

    def test_dsh_sessions_never_replace_one_another(self):
        self.hook("C", "session-start", harness="dsh")
        self.cli("C", "lease", "box", "acquire", "--purpose", "proof", harness="dsh")
        self.hook("C2", "session-start", harness="dsh")  # another session on the same dsh server
        self.assertIn("box: held by", self.cli("A", "lease", "box", "status").stdout)

    def test_a_message_to_a_dsh_session_waits_for_its_next_prompt_or_tool_call(self):
        self.hook("A", "session-start")
        self.hook("C", "session-start", harness="dsh")
        c_name = self.cli("C", "whoami", harness="dsh").stdout.split()[0]
        out = self.cli("A", "post", "heads-up", "--to", c_name).stdout
        self.assertIn("sees this at its next prompt or tool call, or before its current turn ends", out)


class InProcess(unittest.TestCase):
    """Paths that need a running stack, driven in-process with the probe faked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {"SWITCHBOARD_HOME": self.tmp.name, "SWITCHBOARD_ADAPTERS": "none",
               "SWITCHBOARD_CLAUDE_SESSIONS": self.tmp.name + "/none"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        loader = SourceFileLoader("switchboard_bin", str(BIN))
        self.sb = importlib.util.module_from_spec(importlib.util.spec_from_loader("switchboard_bin", loader))
        loader.exec_module(self.sb)
        self.db = self.sb.connect()
        self.a = self.sb.upsert_session(self.db, "sid-A", self.tmp.name, os.getpid())
        self.b = self.sb.upsert_session(self.db, "sid-B", self.tmp.name, os.getpid())
        self.facts = {"running": True, "summary": "running from /w", "served_from": ["/w"],
                      "facts": {"ai-agents alembic": "aaa"}}
        self.sb.observe = lambda _resource: self.facts

    def test_release_flags_a_changed_alembic_stamp_and_the_next_holder_adopts(self):
        self.sb.try_acquire(self.db, "box", self.a, "seed", None)
        self.facts["facts"] = {"ai-agents alembic": "bbb"}
        warnings = self.sb.release_warnings(self.db, self.a, "box", self.sb.lease_row(self.db, "box"), self.facts)
        self.assertEqual(warnings, ["ai-agents alembic changed aaa -> bbb during this lease; restore it or say why it stays"])
        self.db.execute("DELETE FROM leases")
        self.sb.ledger(self.db, self.a, "release", "pass; left running: native", "box")
        mismatch = self.sb.reality_lines(self.db, "box", self.facts, None)[-1]
        self.assertIn("last held by", mismatch)
        self.assertIn("left running: native", mismatch)
        ok, note = self.sb.try_acquire(self.db, "box", self.b, "e2e", None)
        self.assertTrue(ok)
        self.assertIn(f"adopting what {self.a['name']} left running", note)
        direct = self.db.execute("SELECT body FROM posts WHERE to_session = 'sid-A'").fetchone()
        self.assertIn("which you left running", direct["body"])


if __name__ == "__main__":
    unittest.main()
