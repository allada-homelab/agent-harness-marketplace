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
   also read `./references/dataviz/README.md` and run its validator before choosing colors. Start from these validated five-slot categorical palettes and run the validator only if you change them: light on a near-white surface `#0072B2,#009E73,#D55E00,#B2548F,#C77F00`; dark on a near-black surface `#357FB5,#009E73,#D55E00,#A64E97,#C77F00`.
   For a diagram read `./references/diagramming.md`. For anything beyond one viewer's own
   browser storage — shared state, a file download, a model call — read
   `./references/runtime-seam.md` and design for its absence.
2. **Prepare the output dir.** `python3 <skill dir>/artifactctl.py prepare` prints the
   directory (`.artifacts/` under the working directory, git-excluded). The file is
   `<slug-of-title>.html` inside it; a revision overwrites the same file.
3. **Write the page.** Start from the closest template: read `./templates/README.md`, copy
   that file to the output dir as `<slug>.html`, replace its slots and its `DATA`, and keep its
   token block and interaction code — they already satisfy the contract. Only when no template
   is close write the document from scratch with the `write` tool: doctype, head, title,
   description meta, viewport with `viewport-fit=cover`, tokens on `:root`, body; scripts only
   from the CDN allowlist, everything else inline.
4. **Check, then look.** `python3 <skill dir>/artifactctl.py check <file>` — fix every `FAIL`,
   re-run, stop when it prints `ok`. A `WARN` is advice. Then
   `python3 <skill dir>/artifactctl.py render <file>`: it renders the page in headless Chrome
   at phone width, writes `<stem>.png` beside the file and prints any console error; add `--sandbox` to render it inside the same `allow-scripts` frame dsh uses, which surfaces storage access and other runtime errors (a blocked form submit stays silent; the static `sandbox:` rule in `check` catches that); `skipped:`
   means no Chrome is installed and is not a defect. Read the PNG with your file-reading tool
   and look at it the way the user will: an empty bar, overlapping text, an unstyled block or a
   missing section is a defect the static check cannot see. Fix, re-check, re-render. If the
   tool returns the PNG as text rather than an image, rely on the console lines. Build no other
   preview.
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
- Action buttons are `type="button"` with click handlers; a `submit` event never fires in the dsh
  preview.
- Say one plain sentence about the design direction at most; the token plan lives in the
  file, not in the reply.
