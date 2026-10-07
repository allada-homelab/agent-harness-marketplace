---
name: artifacts
description: Build a local HTML artifact — a page, dashboard, report, chart, diagram or small interactive tool — as one self-contained file the user opens locally; design, dataviz and diagramming guidance plus a check-and-deliver flow. Use whenever a page would serve better than prose.
user-invocable: false
harness: [claude, pi, dsh]
tags: [artifacts, design, dataviz]
---

# artifacts

An artifact is one self-contained `.html` file on disk. Nothing hosts it: dsh shows it in the
right sidebar, a browser opens it from its path. No server, no publish step, no runtime.

## When a page beats prose

Decide the treatment; designing is a given. A plan, a memo or a demo gets a utilitarian page:
polished hierarchy, considered spacing, a proper palette, no hero. A landing page, a game, a
tool the user will keep gets an editorial one. If unsure, a well-composed page is always
acceptable. A single fact, a short list or an answer the user will act on at once stays prose.

## Procedure

1. **Read first.** `./references/design.md` — its *Local page contract* is binding; the
   fundamentals and process below it are the craft. For a chart, graph, KPI row or dashboard
   also read `./references/dataviz/README.md` and run its validator before choosing colors.
   For a diagram read `./references/diagramming.md`. For anything that would store, share or
   ask the model read `./references/runtime-seam.md` and design for its absence.
2. **Prepare the output dir.** `python3 <skill dir>/artifactctl.py prepare` prints the
   directory (`.artifacts/` under the working directory, git-excluded). The file is
   `<slug-of-title>.html` inside it; a revision overwrites the same file.
3. **Write the page** with the `write` tool: a complete document (doctype, head, title,
   description meta, viewport with `viewport-fit=cover`, tokens on `:root`, body), scripts only
   from the CDN allowlist, everything else inline.
4. **Check once.** `python3 <skill dir>/artifactctl.py check <file>` — fix every `FAIL`,
   re-run, stop when it prints `ok`. A `WARN` is advice. There is no rendered preview; do not
   build one.
5. **Deliver.**
   - **dsh:** call the `present` tool with `files: [{ path, description }]`, the description
     being the page's one sentence. The card opens the page in the right sidebar, where it runs
     with scripts when *Coding Tools* (Settings → General) is on. Close with one line naming
     the file and that switch.
   - **pi:** run `python3 <skill dir>/artifactctl.py open <file>`. It opens the system browser
     when a display exists and always prints the absolute path. Close with that path.
   - **Claude Code:** this module is normally off here; Claude's own Artifact tool and skills
     apply. If it is on, deliver as for pi.

`<skill dir>` is the directory this SKILL.md sits in (the harness tells you where a skill
loaded from); the script sits beside it. Run it with `python3`, never import it.

## Rules that are not in the references

- One file per artifact; no sibling assets, no multi-page sites.
- Phone width first: dsh is used from a phone.
- Never a download link, never `window.claude`, never a claude.ai URL.
- Say one plain sentence about the design direction at most; the token plan lives in the
  file, not in the reply.
