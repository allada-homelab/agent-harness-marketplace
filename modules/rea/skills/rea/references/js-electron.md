# JS/Electron application analysis with REA

For a JavaScript/Electron app, start with REA's static application
reconstruction; it connects shipped application bytes, JavaScript structure,
Electron process boundaries and native add-ons into one evidence model.

## Static reconstruction

- `rea analyze-javascript-application /analysis/<path>` — reconstructs the
  application statically: bounded directory/ASAR, package, bundle and
  source-map facts, BrowserWindow/preload/contextBridge/IPC wiring,
  utility-process structure, and JavaScript-side native binding references.
- Keep a machine-readable copy of the facts for later querying:
  `rea analyze-javascript-application /analysis/<path> --json > app-evidence.json`,
  then project a view with `rea inspect-analysis-view` on a request like
  `{"source": {"kind": "evidence-file", "path": "app-evidence.json"}, "view": {"kind": "javascript-facts", "property_keys": [], "offset": 0, "limit": 32}}`
  (the `summary` view is the compact default; an evidence file for a large app
  can be hundreds of MB, so always view, never dump).

## Native add-ons

- The JavaScript layer references native add-ons (`.node`, `.so`, Electron
  native modules). Those are Ghidra targets — follow the
  `./native-ghidra.md` workflow and cross-reference the exports against the
  bindings the reconstruction named. The binding names are the bridge between
  the two layers.

## Scope notes

- REA does not evaluate or run the application. Runtime observation (a separate
  REA model, browser/CDP-based) is out of scope for the static commands in this
  module; if runtime evidence is needed, record what is missing in the write-up
  rather than implying the static reconstruction observed it.
- Minified bundles: the reconstruction still recovers structure (modules,
  routes, IPC), but source-level detail is best-effort; report the limitation.
