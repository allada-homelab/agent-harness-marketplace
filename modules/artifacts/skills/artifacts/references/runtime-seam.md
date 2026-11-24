# Runtime seam: `window.artifact`

A page cannot send anything back by itself: the agent reads only the file on disk. In dsh, the
`artifact-bridge` plugin adds one call to pages whose file name ends in `.artifact.html`, so a
page can hand the user's input to the chat. pi and a plain browser tab have no bridge.

## The surface

```js
artifact.submit(text) // → Promise<boolean>
```

It puts `text` (plain text, at most 20,000 characters) into the user's message box in the
session that owns the preview. It never sends the message: the user reads it and presses send,
and the agent gets it as an ordinary turn. It resolves `false` when the text could not be
inserted (the draft is locked by a send in progress, or the text is too long). Nothing else is
on `window.artifact`.

## Rules for every page

- **Feature-detect once at boot.** `const bridge = globalThis.artifact;` Label the hand-over
  button *Send to chat* when it exists, *Copy for chat* (clipboard) when it does not, and fall
  back to the copy path when `submit` resolves `false`. `checklist.html` is the reference.
- **The page works without it.** The bridge needs dsh's *Coding Tools* switch, so pages render
  fully from their own source and keep every other feature when it is absent.
- **The bridge is not storage.** Ticks and notes still live only in the page (and in
  `localStorage` where the browser allows it). Closing the preview without sending loses them;
  say so in the page's intro when that matters.
- **No hosted references.** `window.claude`, `claude.use(`, `claude.ai` and `ArtifactData`
  fail `artifactctl.py check`.
- **Downloads are a path, not a link.** The agent hands the user the file path in its closing
  line; the page never offers `<a download>`.

## How it works

dsh's Document Preview shows a page in an iframe with `sandbox="allow-scripts"` and no
`allow-same-origin`. The plugin registers a renderer for the `.artifact.html` suffix (it ranks
above the built-in HTML renderer only for that suffix), inserts one bootstrap `<script>` after
`<head>` that defines `window.artifact`, and answers its `postMessage` calls from the parent,
accepting only messages from its own frame with that frame's nonce. The parent inserts the text
through the session's composer actions. No host route and no file write is involved.
