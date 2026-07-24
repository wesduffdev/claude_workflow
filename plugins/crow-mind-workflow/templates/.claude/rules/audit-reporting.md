# Rule: Audit & Reporting

Every specialist agent response must be auditable. Report the following in the final
summary so the Orchestrator (and a human) can see exactly what happened:

- **Agent used**
- **Task performed**
- **MCP tools used**
- **Reads performed**
- **Writes attempted**
- **Writes completed**
- **Approvals requested**
- **Approvals received**
- **Failures**
- **Retries**
- **Final outcome**
- **Evidence of completion** (ids, links, before/after — enough to verify)

## Constraints

- **Never expose secrets, tokens, or credentials** in a report.
- Do not paste large sensitive business records wholesale; summarize and reference
  by id/link.
- Report honestly: if a write was denied or a step skipped, say so.

## Machine audit

The `.claude/hooks/mcp-audit.sh` hook (wired via `.claude/settings.json`
`PostToolUse`) appends one JSONL line per `mcp__{{MCP_SERVER}}__*` call to
`.claude/audit/linear-mcp.log` (timestamp, tool, session id, inputs). This is an
audit aid, not an enforcement mechanism, and it cannot by itself attribute a call to
a specific agent. The log is machine-local and git-ignored.
