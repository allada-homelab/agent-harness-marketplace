# browser

One skill, `browser`, plus the `browserctl.mjs` launcher beside it. `browserctl`
maps an *identity* (a named, persistent browser profile) and a *mode* (`auto`
headless, `hybrid` headed) onto an `agent-browser` invocation, so the agent
never composes agent-browser flags itself and never touches your everyday
browser profile.

Requires `agent-browser` on PATH and a Chrome for Testing binary (see
`browserctl doctor`). On a fleet host both are provisioned by the dotfiles
layer; elsewhere install agent-browser from npm and run `agent-browser install`.
