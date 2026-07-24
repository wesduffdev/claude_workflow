# Hooks — MCP Tool Gateway

Hooks are part of the Tool Gateway's control layer. Keep them honest: only wire up
hooks that Claude Code actually supports, and never rely on a hook as the *sole*
enforcement of a policy (enforcement is the `permissions` block in
`../settings.json` plus each agent's `tools:` allow-list).

## Implemented now

- **`mcp-audit.sh`** — a `PostToolUse` hook (matcher `mcp__{{MCP_SERVER}}__.*`,
  wired in `../settings.json`). Appends one JSONL line per Linear MCP call to
  `../audit/linear-mcp.log` (timestamp, tool, session id, permission mode, inputs).
  Never blocks. The audit dir is git-ignored (machine-local).

## Recommended future hooks

As the gateway matures, these are worth adding (verify each against the current
Claude Code hooks docs before implementing — do not invent unsupported hooks):

- **Log tool invocation** — a `PreToolUse` companion to record intent *before* the
  approval prompt (same regex matcher).
- **Detect write operations** — flag `save_*` / `create_*` / `submit_*` / `merge_*`
  in the log for quick review.
- **Block destructive tools** — a `PreToolUse` hook that exits non-zero on
  `delete_*` as defense-in-depth behind the `deny` rule.
- **Require approval before protected writes** — reinforce the `ask` policy for
  writes if a future connection is added without settings coverage.
- **Record execution summaries** — capture each specialist's structured result to an
  execution log.
- **Validate assigned-tools-only** — cross-check a call against the acting agent's
  allow-list (limited today: the hook payload does not identify the sub-agent).

## Notes / limitations

- Hook matchers for MCP tools are **regex** (e.g. `mcp__{{MCP_SERVER}}__.*`), not
  the glob syntax used by `permissions`.
- The `PostToolUse` payload does not include which sub-agent made the call, so
  per-agent attribution is not currently possible from a hook alone.
- `PreToolUse` can block (non-zero exit); `PostToolUse` cannot.
