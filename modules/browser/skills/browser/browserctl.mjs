#!/usr/bin/env node
// browserctl — the browser skill's launcher. Maps an IDENTITY (a persistent,
// dedicated browser profile) and a MODE (auto = headless, hybrid = headed) onto
// one agent-browser invocation, so the agent never composes agent-browser flags
// and never touches the user's everyday browser profile. Zero dependencies:
// node:* only, Node >= 22. agent-browser owns the Chrome process.
//
//   browserctl doctor [--json]
//   browserctl run --identity <name> [--mode auto|hybrid] [--session <id>] -- <agent-browser args...>
//   browserctl attach --identity <name> [--session <id>] (--cdp <port|url> | --auto-connect) -- <agent-browser args...>
//   browserctl identities
//   browserctl export --identity <name> [--session <id>] --out <file>
//   browserctl import --identity <name> [--session <id>] --in <file>
//   browserctl close  --identity <name> [--session <id>]
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, readlinkSync, rmSync, statSync, chmodSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

export const AGENT_BROWSER_VERSION = "0.43.0";
const SUID_SANDBOX = "/opt/google/chrome/chrome-sandbox";
const HOME = homedir();
const ROOT = join(HOME, ".browserctl");
const PROFILES = join(ROOT, "profiles");
const IDENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function die(msg, code = 2) { process.stderr.write(`browserctl: ${msg}\n`); process.exit(code); }

function parse(argv) {
  const opts = {}; const rest = []; let passthrough = null;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (passthrough) { passthrough.push(a); continue; }
    if (a === "--") { passthrough = []; continue; }
    if (a.startsWith("--")) {
      const k = a.slice(2);
      if (k === "json") { opts.json = true; continue; }
      if (k === "auto-connect") { opts.autoConnect = true; continue; }
      const v = argv[++i];
      if (v === undefined) die(`--${k} needs a value`);
      opts[k] = v;
    } else rest.push(a);
  }
  return { opts, rest, passthrough: passthrough || [] };
}

function agentBrowserVersion() {
  const r = spawnSync("agent-browser", ["--version"], { encoding: "utf8" });
  if (r.error || r.status !== 0) return null;
  return (r.stdout.trim().split(/\s+/)[1] || "").replace(/^v/, "");
}

function newestManagedChrome() {
  // agent-browser's own download dir, under the home directory:
  // .agent-browser/browsers/chrome-<ver>/
  const dir = join(HOME, ".agent-browser", "browsers");
  if (!existsSync(dir)) return null;
  const vers = readdirSync(dir).filter((d) => d.startsWith("chrome-")).map((d) => d.slice(7))
    .sort((a, b) => { const x = a.split(".").map(Number), y = b.split(".").map(Number);
      for (let i = 0; i < 4; i++) if ((x[i] || 0) !== (y[i] || 0)) return (y[i] || 0) - (x[i] || 0); return 0; });
  const rels = process.platform === "darwin"
    ? ["Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
       "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
       "chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"]
    : ["chrome", "chrome-linux64/chrome", "chrome-linux-arm64/chrome"];
  for (const v of vers) for (const rel of rels) { const p = join(dir, `chrome-${v}`, rel); if (existsSync(p)) return p; }
  return null;
}

function resolveChrome() {
  const candidates = [process.env.BROWSERCTL_CHROME, join(ROOT, "chrome", "current"),
    process.env.AGENT_BROWSER_EXECUTABLE_PATH, newestManagedChrome()];
  for (const c of candidates) {
    if (!c) continue;
    try { if (!statSync(c).isFile()) continue; } catch { continue; /* dangling link or absent */ }
    // chrome/current is a symlink the installer repoints at a versioned dir;
    // hand agent-browser the target so the launch names the real binary.
    try { return resolve(dirname(c), readlinkSync(c)); } catch { return c; }
  }
  return null;
}

function display() {
  if (process.platform === "darwin") return "native";
  if (process.env.DISPLAY) return "x11";
  if (process.env.WAYLAND_DISPLAY) return "wayland";
  return "none";
}

// Ubuntu 23.10+ AppArmor blocks the unprivileged user namespaces Chrome for
// Testing sandboxes with, and CfT ships no setuid helper — Chrome dies with "No
// usable sandbox". Borrow a system Chrome's setuid helper rather than run
// --no-sandbox against untrusted pages. Returns the helper path, "" when the
// namespace sandbox works, or null when neither is available.
function chromeSandbox() {
  if (process.env.CHROME_DEVEL_SANDBOX) return process.env.CHROME_DEVEL_SANDBOX;
  let restricted = false;
  try { restricted = readFileSync("/proc/sys/kernel/apparmor_restrict_unprivileged_userns", "utf8").trim() === "1"; } catch { /* not Linux, or no such knob */ }
  if (!restricted) return "";
  try { const s = statSync(SUID_SANDBOX); if (s.uid === 0 && (s.mode & 0o4000)) return SUID_SANDBOX; } catch { /* absent */ }
  return null;
}
const NO_SANDBOX = `no usable Chrome sandbox: AppArmor restricts user namespaces and there is no setuid-root ${SUID_SANDBOX} (install google-chrome, or point CHROME_DEVEL_SANDBOX at a setuid chrome-sandbox)`;
const sandboxEnv = (sandbox) => (sandbox ? { ...process.env, CHROME_DEVEL_SANDBOX: sandbox } : process.env);

// A helper on disk proves nothing under no_new_privs (dsh's systemd unit sets
// it): the kernel ignores the setuid bit and Chrome aborts. So doctor launches
// Chrome once, sandboxed, and reports the failure line instead of guessing.
function sandboxProbe(chrome, sandbox) {
  const dir = mkdtempSync(join(tmpdir(), "browserctl-probe-"));
  try {
    const r = spawnSync(chrome, ["--headless=new", `--user-data-dir=${dir}`, "--dump-dom", "about:blank"],
      { encoding: "utf8", timeout: 30000, env: sandboxEnv(sandbox) });
    if (r.status === 0) return null;
    const why = (r.stderr || "").split("\n").find((l) => /sandbox|namespace/i.test(l))?.trim() ?? `exit ${r.status ?? r.signal}`;
    let nnp = false;
    try { nnp = /^NoNewPrivs:\s*1/m.test(readFileSync("/proc/self/status", "utf8")); } catch { /* not Linux */ }
    return `Chrome cannot start with its sandbox here: ${why}` + (nnp
      ? " — this process runs with no_new_privs (e.g. the dsh service), so a setuid helper cannot work; the host needs an AppArmor profile granting Chrome for Testing user namespaces"
      : "");
  } finally { rmSync(dir, { recursive: true, force: true }); }
}

function doctor(opts) {
  const problems = [];
  const ab = agentBrowserVersion();
  if (!ab) problems.push("agent-browser not on PATH");
  else if (ab !== AGENT_BROWSER_VERSION) problems.push(`agent-browser ${ab} installed; this skill expects ${AGENT_BROWSER_VERSION}`);
  const chrome = resolveChrome();
  if (!chrome) problems.push("no Chrome for Testing: expected .browserctl/chrome/current under the home directory (dotfiles installer), $AGENT_BROWSER_EXECUTABLE_PATH, or `agent-browser install`");
  const sandbox = chromeSandbox();
  if (sandbox === null) problems.push(NO_SANDBOX);
  else if (chrome) { const p = sandboxProbe(chrome, sandbox); if (p) problems.push(p); }
  const report = { ok: problems.length === 0, agentBrowser: ab, chrome, node: process.version, display: display(), problems };
  if (opts.json) process.stdout.write(JSON.stringify(report) + "\n");
  else {
    for (const p of problems) process.stdout.write(`problem: ${p}\n`);
    process.stdout.write(`${report.ok ? "ok" : "not ok"}: agent-browser ${ab ?? "-"}, chrome ${chrome ?? "-"}, node ${process.version}, display ${report.display}\n`);
  }
  process.exit(report.ok ? 0 : 2);
}

function identity(opts) {
  const id = opts.identity;
  if (!id || !IDENT.test(id)) die("--identity is required and must match [A-Za-z0-9][A-Za-z0-9._-]*");
  return id;
}

function profileDir(id) {
  const p = join(PROFILES, id);
  mkdirSync(p, { recursive: true, mode: 0o700 });
  chmodSync(p, 0o700);  // recursive:true ignores mode on an existing dir
  return p;
}

function sessionName(opts, id) {
  if (opts.session) return opts.session;
  const h = createHash("sha1").update(process.cwd()).digest("hex").slice(0, 8);
  return `${id}-${h}`;
}

// The tail is appended after the composed flags, so a passthrough copy of any of
// these would win and repoint the launch at the user's everyday browser; --args
// would let an agent launch Chrome with --no-sandbox against untrusted pages.
const RESERVED = new Set(["--profile", "--executable-path", "--session", "--cdp",
  "--auto-connect", "--headed", "--idle-timeout", "--args"]);

function invoke(opts, tail) {
  for (const a of tail) {
    const flag = a.split("=")[0];
    if (RESERVED.has(flag)) die(`${flag} is reserved by browserctl and cannot be passed after --`);
  }
  const id = identity(opts);
  const mode = opts.mode || "auto";
  if (mode !== "auto" && mode !== "hybrid") die("--mode must be auto or hybrid");
  if (mode === "hybrid" && display() === "none") die("--mode hybrid opens a window and this machine has no display (DISPLAY/WAYLAND_DISPLAY unset); use --mode auto, or run on a machine with a GUI");
  const chrome = resolveChrome();
  if (!chrome) die("no Chrome for Testing found — run `browserctl doctor`");
  const sandbox = chromeSandbox();
  if (sandbox === null) die(NO_SANDBOX);
  const env = sandboxEnv(sandbox);
  const args = ["--session", sessionName(opts, id), "--profile", profileDir(id), "--executable-path", chrome, "--pin-tab"];
  // A headed browser is exempt from agent-browser's default idle timeout; a
  // headless one is reaped after 30 min idle so orphaned daemons don't linger.
  if (mode === "hybrid") args.push("--headed"); else args.push("--idle-timeout", "30m");
  const r = spawnSync("agent-browser", [...args, ...tail], { stdio: "inherit", env });
  if (r.error) die(`cannot exec agent-browser: ${r.error.message}`);
  process.exit(r.status ?? 1);
}

// Attach to a browser someone else owns — the user's own Chrome launched with
// --remote-debugging-port, or any externally-owned browser (Electron, remote
// service). Unlike run, it composes no --profile/--executable-path and needs no
// pinned Chrome: the browser is externally owned and keeps its own profile.
// --pin-tab binds the session to its own tab rather than adopting the active one.
function attach(opts, tail) {
  for (const a of tail) {
    const flag = a.split("=")[0];
    if (RESERVED.has(flag)) die(`${flag} is reserved by browserctl and cannot be passed after --`);
  }
  const id = identity(opts);
  const cdp = opts.cdp;
  const auto = opts.autoConnect;
  if (!cdp && !auto) die("attach needs --cdp <port|url> or --auto-connect");
  if (cdp && auto) die("attach takes --cdp OR --auto-connect, not both");
  const args = ["--session", sessionName(opts, id), "--pin-tab"];
  if (cdp) args.push("--cdp", cdp); else args.push("--auto-connect");
  const r = spawnSync("agent-browser", [...args, ...tail], { stdio: "inherit" });
  if (r.error) die(`cannot exec agent-browser: ${r.error.message}`);
  process.exit(r.status ?? 1);
}

const { opts, rest, passthrough } = parse(process.argv.slice(2));
const cmd = rest[0];
switch (cmd) {
  case "doctor": doctor(opts); break;
  case "run": if (!passthrough.length) die("run needs `-- <agent-browser args>`"); invoke(opts, passthrough); break;
  case "attach": if (!passthrough.length) die("attach needs `-- <agent-browser args>`"); attach(opts, passthrough); break;
  case "identities": {
    const names = existsSync(PROFILES)
      ? readdirSync(PROFILES).filter((n) => IDENT.test(n) && statSync(join(PROFILES, n)).isDirectory()).sort()
      : [];
    process.stdout.write(names.map((n) => n + "\n").join("")); break;
  }
  case "export": if (!opts.out) die("export needs --out <file>"); invoke(opts, ["state", "save", opts.out]); break;
  case "import": if (!opts.in) die("import needs --in <file>"); invoke(opts, ["state", "load", opts.in]); break;
  case "close": invoke(opts, ["close"]); break;
  default: die("usage: browserctl doctor|run|attach|identities|export|import|close (see SKILL.md)");
}
