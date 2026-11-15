# browser

One skill, `browser`, plus the `browserctl.mjs` launcher beside it. `browserctl`
maps an *identity* (a named, persistent browser profile) and a *launch option*
(`auto` headless, `hybrid` headed — both the skill's own Chromium; or `attach`,
which drives a browser the user opened) onto an `agent-browser` invocation, so
the agent never composes agent-browser flags itself and never touches your
everyday browser profile.

Requires `agent-browser` on PATH and a Chrome for Testing binary (see
`browserctl doctor`). On a fleet host both are provisioned by the dotfiles
layer; elsewhere install agent-browser from npm and run `agent-browser install`.
`hybrid` needs a display. On Linux hosts whose AppArmor restricts unprivileged
user namespaces (Ubuntu 23.10+), Chrome for Testing has no usable sandbox of its
own; `browserctl` borrows an installed google-chrome's setuid `chrome-sandbox`
(or `CHROME_DEVEL_SANDBOX`) rather than disabling the sandbox, and `doctor`
reports when neither exists.
