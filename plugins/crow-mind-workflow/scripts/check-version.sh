#!/usr/bin/env bash
#
# SessionStart version-check hook for the crow-mind-workflow plugin.
#
# Compares the INSTALLED plugin version (.claude-plugin/plugin.json) against the
# LATEST version published in the marketplace manifest on GitHub, caches the
# verdict to ${CLAUDE_PLUGIN_DATA}/version-status.json, and — only when the
# install is behind — prints a {"systemMessage": ...} JSON object on stdout so
# Claude Code surfaces the update instructions to the user.
#
# Design contract (read by the init-repo and sync-baseline skills):
#
#   ${CLAUDE_PLUGIN_DATA}/version-status.json =
#     {
#       "status": "up-to-date" | "behind" | "unknown",
#       "installed": "<x.y.z>",
#       "latest": "<x.y.z>",
#       "checkedAt": "<ISO-8601 UTC>",
#       "updateInstructions": "<multi-line; empty unless behind>"
#     }
#
# The cache lets every later skill/tool use cheaply re-surface the reminder
# without re-fetching over the network.
#
# This hook is DEFENSIVE by design: any network, parse, or filesystem failure
# degrades to status "unknown", stays SILENT (no stdout), still writes the
# cache, and ALWAYS exits 0 so it can never block a session from starting.
#
# Testability: `check-version.sh --self-test` exercises all three verdicts
# (behind / up-to-date / unknown) with no network access, driven by env
# overrides:
#   CMW_PLUGIN_ROOT   stands in for ${CLAUDE_PLUGIN_ROOT}
#   CMW_PLUGIN_DATA   stands in for ${CLAUDE_PLUGIN_DATA}
#   CMW_LATEST_OVERRIDE   inject the "latest" version (skip the network fetch)
#   CMW_FORCE_NETFAIL=1   simulate a fetch failure (overrides CMW_LATEST_OVERRIDE)

set -u

MANIFEST_URL="https://raw.githubusercontent.com/wesduffdev/claude_workflow/main/.claude-plugin/marketplace.json"
PLUGIN_NAME="crow-mind-workflow"

# Absolute path to this script, so --self-test can re-invoke it as a subprocess.
SELF_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)/$(basename "${BASH_SOURCE[0]}")"

# Overrides win over the Claude-provided env vars (both default to empty so
# `set -u` never trips when a var is unset).
PLUGIN_ROOT="${CMW_PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-}}"
PLUGIN_DATA="${CMW_PLUGIN_DATA:-${CLAUDE_PLUGIN_DATA:-}}"

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# --- version extraction -----------------------------------------------------

# Extract a top-level "version" string from JSON on stdin (installed plugin.json).
extract_installed_version() {
  if command -v jq >/dev/null 2>&1; then
    jq -r '.version // empty' 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
v=d.get("version")
print(v if v else "")' 2>/dev/null
  else
    grep -oE '"version"[[:space:]]*:[[:space:]]*"[^"]+"' | head -n1 \
      | sed -E 's/.*"([^"]+)"[[:space:]]*$/\1/'
  fi
}

# Extract the crow-mind-workflow plugin entry's version from a marketplace
# manifest on stdin.
extract_latest_version() {
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg n "$PLUGIN_NAME" \
      '(.plugins // [])[] | select(.name == $n) | .version' 2>/dev/null | head -n1
  elif command -v python3 >/dev/null 2>&1; then
    PLUGIN_NAME="$PLUGIN_NAME" python3 -c 'import sys,os,json
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
for p in d.get("plugins",[]):
    if p.get("name")==os.environ["PLUGIN_NAME"] and p.get("version"):
        print(p["version"]); break' 2>/dev/null
  else
    # Best-effort fallback: first version string in the manifest.
    grep -oE '"version"[[:space:]]*:[[:space:]]*"[^"]+"' | head -n1 \
      | sed -E 's/.*"([^"]+)"[[:space:]]*$/\1/'
  fi
}

installed_version() {
  [ -n "$PLUGIN_ROOT" ] || return 0
  local file="$PLUGIN_ROOT/.claude-plugin/plugin.json"
  [ -f "$file" ] || return 0
  extract_installed_version < "$file"
}

# Resolve the latest version, honouring the test overrides. Prints the version
# on success; returns non-zero on any failure (caller maps that to "unknown").
latest_version() {
  if [ "${CMW_FORCE_NETFAIL:-}" = "1" ]; then
    return 1
  fi
  if [ -n "${CMW_LATEST_OVERRIDE:-}" ]; then
    printf '%s' "$CMW_LATEST_OVERRIDE"
    return 0
  fi
  command -v curl >/dev/null 2>&1 || return 1
  local body version
  body="$(curl -fsSL --max-time 5 "$MANIFEST_URL" 2>/dev/null)" || return 1
  [ -n "$body" ] || return 1
  version="$(printf '%s' "$body" | extract_latest_version)"
  [ -n "$version" ] || return 1
  printf '%s' "$version"
}

# --- semver compare ---------------------------------------------------------

# Numeric dotted-version compare. Echoes -1 (a<b), 0 (a==b), or 1 (a>b).
# Pads to equal length and treats each component base-10, ignoring any trailing
# non-numeric (e.g. pre-release) suffix.
vercmp() {
  local a="$1" b="$2" i len x y
  local -a A B
  IFS='.' read -r -a A <<< "$a"
  IFS='.' read -r -a B <<< "$b"
  len=${#A[@]}
  (( ${#B[@]} > len )) && len=${#B[@]}
  for (( i = 0; i < len; i++ )); do
    x="${A[i]:-0}"; y="${B[i]:-0}"
    x="${x%%[^0-9]*}"; y="${y%%[^0-9]*}"
    x=$(( 10#${x:-0} )); y=$(( 10#${y:-0} ))
    if (( x < y )); then echo -1; return; fi
    if (( x > y )); then echo 1; return; fi
  done
  echo 0
}

# --- JSON output ------------------------------------------------------------

# Write the cache file. Never fails hard (returns 0 even if the write is skipped).
write_cache() {
  local status="$1" installed="$2" latest="$3" checked_at="$4" instructions="$5"
  [ -n "$PLUGIN_DATA" ] || return 0
  mkdir -p "$PLUGIN_DATA" 2>/dev/null || return 0
  local out="$PLUGIN_DATA/version-status.json"

  if command -v jq >/dev/null 2>&1; then
    jq -n \
      --arg status "$status" \
      --arg installed "$installed" \
      --arg latest "$latest" \
      --arg checkedAt "$checked_at" \
      --arg updateInstructions "$instructions" \
      '{status:$status, installed:$installed, latest:$latest, checkedAt:$checkedAt, updateInstructions:$updateInstructions}' \
      > "$out" 2>/dev/null || return 0
  elif command -v python3 >/dev/null 2>&1; then
    CMW_S="$status" CMW_I="$installed" CMW_L="$latest" CMW_C="$checked_at" CMW_U="$instructions" \
      python3 -c 'import os,json
rec={"status":os.environ["CMW_S"],"installed":os.environ["CMW_I"],"latest":os.environ["CMW_L"],"checkedAt":os.environ["CMW_C"],"updateInstructions":os.environ["CMW_U"]}
print(json.dumps(rec, indent=2))' > "$out" 2>/dev/null || return 0
  fi
  return 0
}

# Print {"systemMessage": "<msg>"} on stdout, JSON-escaped.
emit_system_message() {
  local msg="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -cn --arg m "$msg" '{systemMessage:$m}'
  elif command -v python3 >/dev/null 2>&1; then
    CMW_M="$msg" python3 -c 'import os,json; print(json.dumps({"systemMessage":os.environ["CMW_M"]}))'
  fi
}

# Compose the behind-message / updateInstructions text.
update_instructions() {
  local installed="$1" latest="$2"
  printf 'crow-mind-workflow: update available — %s (installed %s).\nUpdate with:\n  /plugin marketplace update crow-mind\n  /plugin update crow-mind-workflow@crow-mind' \
    "$latest" "$installed"
}

# Read a string field from the existing cache. Prints empty when the cache or
# the field is absent. jq/python3 recover multi-line values (updateInstructions);
# the grep last-resort cannot, which is an accepted degraded mode.
read_cache_field() {
  local field="$1" file
  [ -n "$PLUGIN_DATA" ] || return 0
  file="$PLUGIN_DATA/version-status.json"
  [ -f "$file" ] || return 0
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg f "$field" '.[$f] // empty' "$file" 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import sys,json
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
v=d.get(sys.argv[2])
print(v if v else "")' "$file" "$field" 2>/dev/null
  else
    grep -oE "\"$field\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$file" | head -n1 \
      | sed -E 's/.*:[[:space:]]*"(.*)"[[:space:]]*$/\1/'
  fi
}

# --- main -------------------------------------------------------------------

run_check() {
  local checked_at installed latest status instructions=""
  checked_at="$(now_iso)"

  installed="$(installed_version)"
  [ -n "$installed" ] || installed="unknown"

  if latest="$(latest_version)"; then
    if [ "$installed" = "unknown" ] || [ -z "$latest" ]; then
      status="unknown"
      [ -n "$latest" ] || latest="unknown"
    elif [ "$(vercmp "$installed" "$latest")" = "-1" ]; then
      status="behind"
    else
      status="up-to-date"
    fi
  else
    status="unknown"
    latest="unknown"
  fi

  # A fresh "unknown" (network/parse failure) must not clobber a prior DEFINITIVE
  # verdict: a genuinely out-of-date install should keep nagging through an
  # outage. Preserve only an ALREADY-known verdict — never invent one. checkedAt
  # still refreshes below because run_check always writes the fresh timestamp.
  if [ "$status" = "unknown" ]; then
    local prior
    prior="$(read_cache_field status)"
    if [ "$prior" = "behind" ]; then
      status="behind"
      installed="$(read_cache_field installed)"
      latest="$(read_cache_field latest)"
      instructions="$(read_cache_field updateInstructions)"
    elif [ "$prior" = "up-to-date" ]; then
      status="up-to-date"
      installed="$(read_cache_field installed)"
      latest="$(read_cache_field latest)"
    fi
  fi

  # Recompute the message only if we do not already have it (fresh "behind", or a
  # preserved "behind" whose cached text somehow came back empty).
  if [ "$status" = "behind" ] && [ -z "$instructions" ]; then
    instructions="$(update_instructions "$installed" "$latest")"
  fi

  write_cache "$status" "$installed" "$latest" "$checked_at" "$instructions"

  if [ "$status" = "behind" ]; then
    emit_system_message "$instructions"
  fi

  return 0
}

# --- self-test --------------------------------------------------------------

# Read the cached .status field, robust across jq/python3/grep.
cache_status() {
  local file="$1/version-status.json"
  [ -f "$file" ] || { printf '(missing)'; return; }
  if command -v jq >/dev/null 2>&1; then
    jq -r '.status // "(none)"' "$file" 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import sys,json;print(json.load(open(sys.argv[1])).get("status","(none)"))' "$file" 2>/dev/null
  else
    grep -oE '"status"[[:space:]]*:[[:space:]]*"[^"]+"' "$file" | head -n1 \
      | sed -E 's/.*"([^"]+)"[[:space:]]*$/\1/'
  fi
}

run_self_test() {
  local tmp root fails=0
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/cmw-vc-selftest.XXXXXX")" || {
    echo "FAIL: could not create temp dir"; return 1;
  }
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" EXIT

  root="$tmp/root"
  mkdir -p "$root/.claude-plugin"
  printf '{\n  "name": "crow-mind-workflow",\n  "version": "0.1.0"\n}\n' \
    > "$root/.claude-plugin/plugin.json"

  echo "crow-mind-workflow version-check self-test (no network):"

  # Each case runs against its own fresh cache dir so cross-contamination can
  # never mask the preservation behaviour. (d)/(e) deliberately REUSE the dir a
  # prior case populated, to prove an existing verdict survives an outage.
  local out st da db dc df
  da="$tmp/data-a"; db="$tmp/data-b"; dc="$tmp/data-c"; df="$tmp/data-f"
  mkdir -p "$da" "$db" "$dc" "$df"

  # (a) installed 0.1.0 < latest 0.2.0 -> behind, systemMessage emitted.
  out="$(CMW_PLUGIN_ROOT="$root" CMW_PLUGIN_DATA="$da" CMW_LATEST_OVERRIDE="0.2.0" \
    bash "$SELF_PATH" 2>/dev/null)"
  st="$(cache_status "$da")"
  if printf '%s' "$out" | grep -q '"systemMessage"' && [ "$st" = "behind" ]; then
    echo "  (a) behind                 : PASS  (systemMessage emitted, cache=behind)"
  else
    echo "  (a) behind                 : FAIL  (stdout=[$out] cacheStatus=[$st])"; fails=1
  fi

  # (b) installed 0.1.0 == latest 0.1.0 -> up-to-date, silent.
  out="$(CMW_PLUGIN_ROOT="$root" CMW_PLUGIN_DATA="$db" CMW_LATEST_OVERRIDE="0.1.0" \
    bash "$SELF_PATH" 2>/dev/null)"
  st="$(cache_status "$db")"
  if [ -z "$out" ] && [ "$st" = "up-to-date" ]; then
    echo "  (b) up-to-date             : PASS  (silent, cache=up-to-date)"
  else
    echo "  (b) up-to-date             : FAIL  (stdout=[$out] cacheStatus=[$st])"; fails=1
  fi

  # (c) network failure, no prior cache -> unknown, silent.
  out="$(CMW_PLUGIN_ROOT="$root" CMW_PLUGIN_DATA="$dc" CMW_FORCE_NETFAIL=1 \
    bash "$SELF_PATH" 2>/dev/null)"
  st="$(cache_status "$dc")"
  if [ -z "$out" ] && [ "$st" = "unknown" ]; then
    echo "  (c) unknown (no prior)     : PASS  (silent, cache=unknown)"
  else
    echo "  (c) unknown (no prior)     : FAIL  (stdout=[$out] cacheStatus=[$st])"; fails=1
  fi

  # (d) prior cache=behind (from (a)) + outage -> stays behind AND keeps nagging.
  out="$(CMW_PLUGIN_ROOT="$root" CMW_PLUGIN_DATA="$da" CMW_FORCE_NETFAIL=1 \
    bash "$SELF_PATH" 2>/dev/null)"
  st="$(cache_status "$da")"
  if printf '%s' "$out" | grep -q '"systemMessage"' && [ "$st" = "behind" ]; then
    echo "  (d) behind survives outage : PASS  (systemMessage emitted, cache=behind)"
  else
    echo "  (d) behind survives outage : FAIL  (stdout=[$out] cacheStatus=[$st])"; fails=1
  fi

  # (e) prior cache=up-to-date (from (b)) + outage -> stays up-to-date, silent.
  out="$(CMW_PLUGIN_ROOT="$root" CMW_PLUGIN_DATA="$db" CMW_FORCE_NETFAIL=1 \
    bash "$SELF_PATH" 2>/dev/null)"
  st="$(cache_status "$db")"
  if [ -z "$out" ] && [ "$st" = "up-to-date" ]; then
    echo "  (e) up-to-date survives    : PASS  (silent, cache=up-to-date)"
  else
    echo "  (e) up-to-date survives    : FAIL  (stdout=[$out] cacheStatus=[$st])"; fails=1
  fi

  # (f) no prior cache + outage -> unknown, silent (never invent a verdict).
  out="$(CMW_PLUGIN_ROOT="$root" CMW_PLUGIN_DATA="$df" CMW_FORCE_NETFAIL=1 \
    bash "$SELF_PATH" 2>/dev/null)"
  st="$(cache_status "$df")"
  if [ -z "$out" ] && [ "$st" = "unknown" ]; then
    echo "  (f) no-prior stays unknown : PASS  (silent, cache=unknown)"
  else
    echo "  (f) no-prior stays unknown : FAIL  (stdout=[$out] cacheStatus=[$st])"; fails=1
  fi

  if [ "$fails" -eq 0 ]; then
    echo "PASS: all six version-check cases behave correctly."
    return 0
  fi
  echo "FAIL: one or more self-test cases did not pass."
  return 1
}

# --- dispatch ---------------------------------------------------------------

if [ "${1:-}" = "--self-test" ]; then
  run_self_test
  exit $?
fi

run_check
exit 0
