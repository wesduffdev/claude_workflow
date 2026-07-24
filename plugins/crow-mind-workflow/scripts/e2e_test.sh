#!/usr/bin/env bash
#
# e2e_test.sh — end-to-end proof of the whole crow-mind-workflow chain.
#
# Proves the whole chain fits together, end to end:
#
#   (a) stamp        drives stamp.py against a throwaway temp repo: init-repo lays a
#                    coherent governance tree + baseline manifest
#   (b) sync         drives sync_baseline.py against that repo: it reports drift, then
#                    --apply repairs it
#   (c) version      runs check-version.sh's offline --self-test (behind / current /
#                    offline) — it would otherwise need the network
#   (d) wiki         runs publish_wiki.py's offline --self-test (render + gated publish)
#                    — it would otherwise need to clone/push a wiki
#
# Steps (a) and (b) are temp-dir drives of the real scripts; (c) and (d) delegate to
# each script's own offline self-test, the network-free way to exercise them here.
#
# Dependency-light: bash + coreutils + python3 (already required by the plugin).
# Prints a clear PASS/FAIL for every assertion, cleans up its temp dirs, and exits
# 0 only when every step passed. This is the repo's runnable green bar.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
SAMPLE_SLOTS="$SCRIPT_DIR/sample-slots.json"
PY="${PYTHON:-python3}"

command -v "$PY" >/dev/null 2>&1 || { echo "FATAL: python3 not found on PATH"; exit 2; }

TMPROOT="$(mktemp -d "${TMPDIR:-/tmp}/cmw-e2e.XXXXXX")" || { echo "FATAL: mktemp failed"; exit 2; }
# shellcheck disable=SC2064
trap "rm -rf '$TMPROOT'" EXIT

FAILS=0
pass() { echo "  PASS  $1"; }
fail() { echo "  FAIL  $1"; FAILS=$((FAILS + 1)); }
# assert <label> <condition-rc>: caller runs the test, passes its exit status.
check() { if [ "$2" -eq 0 ]; then pass "$1"; else fail "$1"; fi; }

banner() { echo; echo "=== $1 ==="; }

# --------------------------------------------------------------------------- #
# (a) stamp — init-repo lays a coherent governance tree
# --------------------------------------------------------------------------- #
banner "(a) stamp: init-repo stamps a target repo"
TARGET="$TMPROOT/stamped-repo"
mkdir -p "$TARGET"
"$PY" "$SCRIPT_DIR/stamp.py" --slots "$SAMPLE_SLOTS" --target "$TARGET" --mode root
check "stamp.py exited 0" $?

[ -f "$TARGET/CLAUDE.md" ]; check "CLAUDE.md at repo root" $?
for sub in rules agents skills hooks; do
  [ -d "$TARGET/.claude/$sub" ]; check ".claude/$sub/ present" $?
done
[ -f "$TARGET/.claude/settings.json" ]; check ".claude/settings.json present" $?
[ -x "$TARGET/.githooks/pre-commit" ]; check ".githooks/pre-commit present + executable" $?
[ -x "$TARGET/.githooks/pre-push" ]; check ".githooks/pre-push present + executable" $?
[ -f "$TARGET/.claude/.workflow-baseline.json" ]; check ".claude/.workflow-baseline.json present" $?
[ -f "$TARGET/.github/pull_request_template.md" ]; check "PR template under .github/" $?

# No unsubstituted placeholder must survive anywhere in the stamped tree.
if grep -rq '{{' "$TARGET"; then fail "no '{{' anywhere in stamped tree"
else pass "no '{{' anywhere in stamped tree"; fi

# --------------------------------------------------------------------------- #
# (b) sync — the plugin moves ahead of the stamp; drift is reported and repaired
# --------------------------------------------------------------------------- #
banner "(b) sync-baseline: simulate the plugin moving ahead, then repair"
DRIFT_FILE=".claude/rules/ticketing.md"

# Simulate the repo lagging the plugin two ways at once: roll the recorded plugin
# version back (version-behind) AND make one recorded file read as an OLD variant
# whose hash matches the manifest (so it classifies as 'behind' — a plugin template
# that moved on — not a local edit).
"$PY" - "$TARGET" "$DRIFT_FILE" <<'PY'
import hashlib, json, sys
from pathlib import Path

target, drift = Path(sys.argv[1]), sys.argv[2]
baseline = target / ".claude" / ".workflow-baseline.json"
manifest = json.loads(baseline.read_text(encoding="utf-8"))

manifest["pluginVersion"] = "0.0.1"
manifest["templateSetVersion"] = "0.0.1"

on_disk = target / drift
old_variant = on_disk.read_text(encoding="utf-8") + "\n<!-- OLD VARIANT (simulated pre-drift) -->\n"
on_disk.write_text(old_variant, encoding="utf-8")
for entry in manifest["files"]:
    if entry["path"] == drift:
        entry["sha256"] = hashlib.sha256(old_variant.encode("utf-8")).hexdigest()

baseline.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY
# Surface a broken setup here rather than as a confusing "expected drift, got in-sync"
# failure two assertions downstream.
check "drift setup succeeded" $?

echo "--- report (expect drift, exit 3) ---"
"$PY" "$SCRIPT_DIR/sync_baseline.py" --target "$TARGET"
rc=$?; [ "$rc" -eq 3 ]; check "report exits 3 (drift detected)" $?

echo "--- apply (expect repair, exit 0) ---"
"$PY" "$SCRIPT_DIR/sync_baseline.py" --target "$TARGET" --apply
rc=$?; [ "$rc" -eq 0 ]; check "--apply exits 0 (repaired, nothing left to do)" $?

# The behind marker must be gone and the version bumped back to the installed one.
if grep -q "OLD VARIANT" "$TARGET/$DRIFT_FILE"; then fail "behind file was re-rendered (marker gone)"
else pass "behind file was re-rendered (marker gone)"; fi
"$PY" - "$TARGET" "$SCRIPT_DIR" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
import stamp
installed = json.loads((Path(stamp.PLUGIN_JSON_PATH)).read_text())["version"]
recorded = json.loads((Path(sys.argv[1]) / ".claude" / ".workflow-baseline.json").read_text())["pluginVersion"]
sys.exit(0 if recorded == installed else 1)
PY
check "manifest pluginVersion bumped to the installed version" $?

echo "--- re-report (expect in sync, exit 0) ---"
"$PY" "$SCRIPT_DIR/sync_baseline.py" --target "$TARGET"
rc=$?; [ "$rc" -eq 0 ]; check "re-report exits 0 (in sync)" $?

# --------------------------------------------------------------------------- #
# (c) version-check — behind / current / offline
# --------------------------------------------------------------------------- #
banner "(c) version-check: behind / current / offline verdicts"
bash "$SCRIPT_DIR/check-version.sh" --self-test
check "check-version.sh --self-test exits 0" $?

# --------------------------------------------------------------------------- #
# (d) wiki publish — Workflow page renders; publish is gated (no network)
# --------------------------------------------------------------------------- #
banner "(d) publish-wiki: Workflow page renders, publishing gated (no network)"
"$PY" "$SCRIPT_DIR/publish_wiki.py" --self-test
check "publish_wiki.py --self-test exits 0" $?

# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
echo
if [ "$FAILS" -eq 0 ]; then
  echo "PASS: crow-mind-workflow end-to-end chain is green (stamp -> sync -> version -> wiki)."
  exit 0
fi
echo "FAIL: $FAILS assertion(s) failed."
exit 1
