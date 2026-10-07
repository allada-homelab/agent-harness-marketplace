# Runtime seam (phase 2 — specified, not built)

Claude's hosted artifacts expose `window.claude.use(name)` for shared state, downloads and
model calls. Nothing local provides that yet. This page is the contract a local runtime will
honour, so a page written today keeps working the day one exists.

## Rules for every page, today

- **Design for absence.** `window.artifact` is `undefined` in this phase. The page renders
  fully from the state in its own source: example rows clearly marked as examples, or the
  user's real data inlined. Never leave a frame empty "until the store answers".
- **Feature-detect, never assume.** `const rt = globalThis.artifact; if (rt) { … }` — one
  check at boot; no polling, no retries, no error shown when it is absent.
- **No hosted references.** `window.claude`, `claude.use(`, `claude.ai` and `ArtifactData`
  fail `artifactctl.py check`.
- **Browser storage stays a convenience.** A remembered tab or filter in `localStorage`,
  wrapped in try/catch; nothing the user would miss when it is gone.
- **Downloads are a path, not a link.** Until the runtime exists, the agent hands the user
  the file path in its closing line; the page never offers `<a download>`.

## What `window.artifact` will be

`artifact.use(name)` resolves to one of three objects, with the method shapes of the upstream
`claude.use` capabilities of the same name, so a port is a shim rather than a rewrite:

| name        | surface                                                                                        |
|-------------|------------------------------------------------------------------------------------------------|
| `db`        | `doc(path)` / `collection(path)` with `get` `set` `update` `delete`, `where` `orderBy` `limit`, `onSnapshot(cb)` |
| `downloads` | `save({ filename, data })` — resolves after the viewer confirms                                 |
| `sample`    | `sample(input, opts)` → `{ text, truncated }`; `opts.onText` streams; routed to the harness's own model |

`user`, `room`, `comments`, `assets`, `files` and `mcp` are out of scope until a page needs
them. `use()` of an unknown name rejects with `not_granted`.

## Where it will live

dsh's Document Preview shows the page in an iframe with `sandbox="allow-scripts"` and no
`allow-same-origin`: the parent cannot assign into that opaque-origin child, and a page with
no listener cannot be reached by `postMessage` alone. So the runtime arrives child-side. A
dsh client plugin (dotfiles, `agents/harnesses/dsh/plugins/`) registers its own `html`
document renderer, ranked above the built-in, that prepends one inline bootstrap `<script>`
to the file's bytes before building the Blob iframe. The bootstrap defines `window.artifact`
and bridges every call over `postMessage` to the plugin's parent half, which forwards to a
host route behind the shared ui-kit fence and secrets policy. It runs before the page's own
scripts, so a page written today that feature-detects at boot needs no change. pi has no
viewer of its own; it gets the same page contract and no runtime until one exists. That
phase gets its own spec; nothing in this module depends on it.
