# agent-browser vocabulary used by this skill (0.37.1)

Everything below goes after `browserctl run --identity <id> --session <s> --`.

| Task | Command |
|---|---|
| open a page | `open <url>` |
| current URL / title | `get url` · `get title` |
| interactive snapshot (the one to act on) | `snapshot -i` |
| compact / scoped snapshot | `snapshot -i -c` · `snapshot -i -s "<css>"` |
| click / fill / type / press | `click @e3` · `fill @e2 "text"` · `type @e2 "text"` · `press Enter` |
| select / scroll | `select @e4 "Option"` · `scroll down` |
| wait | `wait "<css>"` · `wait --text "Welcome"` · `wait --url "**/dashboard" --timeout 120000` · `wait --load networkidle` |
| screenshot | `screenshot [path]` · `screenshot --full [path]` |
| page text | `get text` |
| tabs | `tab list` · `tab new <url>` · `tab t2` |
| save / load auth | `state save <file>` · `state load <file>` (prefer `browserctl export/import`) |

## Reading a snapshot

The tree is Playwright-style, one node per line, refs in brackets:

```
- heading "Log in" [level=1, ref=e1]
- textbox "Email" [ref=e2]
- button "Continue" [ref=e3]
```

Act with `@` + the ref: `click @e3`. Refs are reassigned on every snapshot.

## Exit codes

Non-zero means the command failed; the message is on stderr. `tab_gone` means
the operator closed the pinned tab — recover with `tab new <url>`, never by
guessing another tab.
