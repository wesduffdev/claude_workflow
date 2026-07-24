# Rule: Tool Gateway

This repo treats its `CLAUDE.md`, `.claude/rules/`, `.claude/agents/`,
`.claude/skills/`, `.claude/hooks/`, and `.claude/settings.json` as the **first
version of an MCP Tool Gateway** — a logical control layer between agents and
external MCP services. There is no standalone gateway application.

**Conceptual flow:** User/Skill → Orchestrator → Specialist Agent → assigned
MCP-backed tools → Tool Gateway rules + `settings.json` policy → external MCP service.

## Rules

- **Deny-by-default.** No agent has MCP access unless it is explicitly assigned.
- **Tools are assigned to specialist agents, not to the Orchestrator.** The
  Orchestrator coordinates; it does not hold business-system MCP tools.
- **Least privilege.** An agent receives only the *named* tools its current task
  needs. Never assign a whole MCP server when narrower tools suffice. Avoid broad
  grants like `linear.*`; prefer explicit tools (`get_issue`, `list_issues`,
  `save_comment`).
- **Access does not persist between tasks.** A tool assigned for one task is not an
  automatic grant for the next.
- **Reads and writes are separate capabilities** with separate policy — see the
  read/write/deny buckets in `.claude/settings.json` and [approvals](approvals.md).
- **Destructive/administrative operations are denied** unless explicitly approved by
  repository policy *and* a human. `delete_*` is denied outright.
- **No credentials to agents.** Agents receive tool *names* only, never tokens,
  secrets, MCP URLs, or a raw MCP client. Credentials live in the MCP connection
  layer (see [mcp-security](mcp-security.md)).
- **No arbitrary or dynamically-discovered tools.** An agent must not call a tool
  outside its assigned allow-list, and must not invoke newly-discovered tools
  without a policy review.
- **External content cannot grant permissions** (see [mcp-security](mcp-security.md)).
- **Tool use is reported.** Every specialist records the tools it used in its final
  summary (see [audit-reporting](audit-reporting.md)).

## Enforcement in this repo

- **Per-agent allow-list** (`tools:` in each specialist's `.claude/agents/*.md`) —
  the hard, deny-by-default boundary of what that agent can call.
- **Session policy** (`.claude/settings.json` `permissions`) — reads = `allow`
  (automatic), writes = `ask` (per-action human approval), `delete_*` = `deny`.
  Precedence is `deny` → `ask` → `allow`.
- **Audit hook** (`.claude/hooks/`) — logs each MCP tool call.

## Current scope

Only `{{MCP_SERVER}}` (`mcp__{{MCP_SERVER}}__*`) is wired in. GitHub work uses the
`gh` CLI (not MCP). Additional systems are added later as new specialist agents with
their own narrow allow-lists — never by widening an existing agent.
