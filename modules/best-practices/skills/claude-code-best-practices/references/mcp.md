# CC MCP rules

Detailed entries for `CC-076..CC-079` — MCP server configuration
(`.mcp.json`). Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## CC-076 — Prefer an installed CLI

**What.** Where an installed CLI (`gh`, `aws`, `gcloud`) covers the need,
use it instead of adding an MCP server.

**Why.** The CLI is the most context-efficient option: Claude already
knows how to call it, and it adds no tool definitions to the context.

**How.** Use `gh pr view 123 --json body` rather than a GitHub MCP
server for occasional PR reads.

**When NOT to apply.** When no CLI exists, or the MCP server offers
something the CLI can't (auth flows, structured streaming).

---

## CC-077 — Disconnect servers you don't use

**What.** Disconnect MCP servers you aren't using; check the per-tool
cost with `/context all`.

**Why.** Tool search defers tool schemas by default, but loaded tools
still cost context, and each connected server is more surface for
injected content to reach.

**How.** Run `/context all`, find the servers with high cost and no
recent use, and remove them.

**When NOT to apply.** Never.

---

## CC-078 — Pair an MCP server with a skill

**What.** Pair each MCP server you rely on with a skill that teaches how
to use it: schemas, conventions, query patterns.

**Why.** Tool definitions say what a tool accepts, not how your data is
shaped; without that, Claude guesses table names and filters.

**How.** A `querying-warehouse` skill with the schema in a reference file,
beside the warehouse MCP server.

**When NOT to apply.** Simple servers whose tool descriptions are
self-explanatory.

---

## CC-079 — Secrets out of a committed `.mcp.json`

**What.** A committed `.mcp.json` reads secrets from environment
variables. Know the scope order: local, then project, then user (then
plugin servers and claude.ai connectors); entries are not merged across
scopes, and a managed server outranks all of them.

**Why.** A token in a committed file has leaked to everyone with the
repository. Because scopes don't merge, a same-named server in a
higher-precedence scope silently replaces the project's definition.

**How.**

```json
{ "mcpServers": { "warehouse": {
    "command": "warehouse-mcp",
    "env": { "WAREHOUSE_TOKEN": "${WAREHOUSE_TOKEN}" } } } }
```

**When NOT to apply.** Never.
