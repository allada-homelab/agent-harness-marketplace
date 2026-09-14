# Handoff: when the agent needs a human in the browser

Trigger: after navigating, the snapshot shows a password or one-time-code
field, a "Sign in" heading or primary button, a CAPTCHA frame, or the URL is on
an identity-provider host (`accounts.google.com`, `login.microsoftonline.com`,
`github.com/login`, …). Snapshot content is the primary signal; the host list
is a shortcut.

## In a chat harness (Claude Code, pi, dsh)

1. Reopen the same URL in a window:
   `browserctl run --identity <id> --mode hybrid --session <s> -- open <url>`
   (the profile is shared between modes, so nothing is lost).
2. Tell the operator, in one message: which identity, which site, what to do
   ("sign in with the work account, finish MFA"), and that they should reply
   `done` when the page they expect is showing. If `browserctl doctor` reports
   display `none`, say so — there is no window to act in and the task cannot
   continue on this host.
3. Wait for the reply. Do not poll the browser or auto-detect completion:
   single-sign-on bounces through several hosts and a URL alone is not proof.
4. After `done`: `snapshot -i` in the same session and continue. Later tasks
   can use `--mode auto` with the same identity; the login is on disk.

Cancel: if the operator says stop, `browserctl close --identity <id> --session
<s>` and report.
