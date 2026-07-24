#!/usr/bin/env bash
#
# PostToolUse audit hook for the MCP Tool Gateway.
# Wired via .claude/settings.json (matcher: mcp__{{MCP_SERVER}}__.*).
# Appends ONE JSONL line per {{MCP_SERVER}} MCP call to the audit log.
#
# This is an AUDIT AID, not an enforcement mechanism (enforcement is the
# permissions block in settings.json + each agent's tools: allow-list). It
# cannot reliably attribute a call to a specific sub-agent. It never blocks.

set -uo pipefail

DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
LOG_DIR="$DIR/.claude/audit"
LOG="$LOG_DIR/linear-mcp.log"
mkdir -p "$LOG_DIR" 2>/dev/null || true

input="$(cat)"

if command -v jq >/dev/null 2>&1; then
  printf '%s' "$input" | jq -c \
    '{ts: (now|todate), tool: .tool_name, session: .session_id, mode: .permission_mode, input: (.tool_input // {})}' \
    >> "$LOG" 2>/dev/null || true
elif command -v python3 >/dev/null 2>&1; then
  printf '%s' "$input" | python3 -c '
import sys, json, datetime
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
rec = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "tool": d.get("tool_name"),
    "session": d.get("session_id"),
    "mode": d.get("permission_mode"),
    "input": d.get("tool_input", {}),
}
try:
    with open(sys.argv[1], "a") as f:
        f.write(json.dumps(rec) + "\n")
except Exception:
    pass
' "$LOG" 2>/dev/null || true
fi

exit 0
