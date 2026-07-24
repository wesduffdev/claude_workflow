#!/usr/bin/env python3
"""Detect (and, when approved, repair) drift between a stamped repo and the plugin.

``render.py`` substitutes placeholders; ``stamp.py`` places the rendered tree and
records a baseline manifest. This script is the *reconciliation* layer on top of
both: it re-renders the plugin's CURRENT templates with the slot values recorded at
stamp time and compares the result against what is actually on disk, so it can tell
apart three very different situations that a naive diff conflates:

    * the plugin's template moved on since the stamp        -> ``behind``
    * the user hand-edited a stamped governance file        -> ``local-modification``
    * both happened at once                                 -> ``conflict``

The distinction matters because the repair path must **never silently lose a user's
edits**: ``--apply`` updates ``behind`` (and restores ``missing``) files freely, but
leaves ``local-modification`` / ``conflict`` files untouched unless ``--force`` is
given.

CLI
---
::

    sync_baseline.py --target <repo-dir> [--apply] [--force] [--self-test]

Default (no ``--apply``) is **report-only**: it prints a categorized drift report
and exits ``0`` when the repo is in sync or ``3`` when any drift is found (so a
caller can branch on it). ``2`` is reserved for errors (repo not stamped, bad
manifest). ``--apply`` re-renders and writes the safe categories, refreshes the
manifest (recomputes hashes, adds new files, bumps the version, restamps the time),
and exits ``3`` if anything still needs manual attention (skipped edits / unfillable
new slots) or ``0`` otherwise.

Self-test (no network)::

    sync_baseline.py --self-test

Drives the whole flow against throwaway temp repos — a clean stamp, a simulated
template drift, a simulated local edit, slot drift, a new template, and a
version-behind manifest — asserting each is classified and repaired correctly. Exits
non-zero on the first failed assertion; prints a PASS summary otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

# Reuse the shared render + stamp modules — substitution, the connectivity-strip,
# hashing and the baseline location all live in exactly one place, so this script's
# notion of "what a fresh stamp would produce" stays byte-for-byte identical to what
# stamp.py actually writes. Both resolve their own paths from __file__, so importing
# them is CWD-independent.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import render  # noqa: E402
import stamp  # noqa: E402

PLUGIN_DIR = SCRIPT_DIR.parent
TEMPLATES_DIR = PLUGIN_DIR / "templates"
SLOTS_YML_PATH = TEMPLATES_DIR / "slots.yml"
PLUGIN_JSON_PATH = PLUGIN_DIR / ".claude-plugin" / "plugin.json"

PLUGIN_NAME = stamp.PLUGIN_NAME
BASELINE_RELPATH = stamp.BASELINE_RELPATH
TEMPLATE_PREFIX = "templates/"

# Report-only exits 0 (in sync) / 3 (drift found); 2 is reserved for hard errors.
EXIT_OK = 0
EXIT_ERROR = 2
EXIT_DRIFT = 3

# File-drift classifications. See module docstring for the semantics.
IN_SYNC = "in-sync"
BEHIND = "behind"
LOCAL_MOD = "local-modification"
CONFLICT = "conflict"
MISSING = "missing"
OBSOLETE = "obsolete"  # recorded file whose source template was removed from the plugin


class SyncError(Exception):
    """Raised when a sync cannot proceed (repo not stamped, unreadable manifest)."""


# --------------------------------------------------------------------------- #
# Plugin + manifest inputs
# --------------------------------------------------------------------------- #
def _read_installed_version() -> str:
    """Return the ``version`` of the installed plugin (from plugin.json)."""
    data = json.loads(PLUGIN_JSON_PATH.read_text(encoding="utf-8"))
    version = data.get("version")
    if not version:
        raise SyncError(f"no version in {PLUGIN_JSON_PATH}")
    return str(version)


def _read_manifest(target: Path) -> dict:
    """Load the baseline manifest a repo was stamped with, or fail clearly."""
    baseline = target / BASELINE_RELPATH
    if not baseline.is_file():
        raise SyncError(
            f"{target} is not stamped by {PLUGIN_NAME} "
            f"(no {BASELINE_RELPATH.as_posix()}). Run the init-repo skill first."
        )
    try:
        manifest = json.loads(baseline.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SyncError(f"baseline manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict) or "files" not in manifest:
        raise SyncError("baseline manifest is malformed (no 'files' array)")
    return manifest


def _current_slots() -> dict:
    """Return ``{slot key: required?}`` for the plugin's current ``templates/slots.yml``.

    A focused, stdlib-only read of the ``- key: NAME`` / ``required: true|false`` lines
    — no YAML dependency, matching how render/stamp stay dependency-free. The
    ``required`` flag matters because an *optional* slot left empty (e.g. the blank
    ``CONNECTIVITY_CMD``) is legitimate, not drift.
    """
    slots = {}
    current = None
    for line in SLOTS_YML_PATH.read_text(encoding="utf-8").splitlines():
        key_match = re.match(r"\s*-\s*key:\s*([A-Za-z_][A-Za-z0-9_]*)", line)
        if key_match:
            current = key_match.group(1)
            slots[current] = False  # assume optional until a `required:` line says otherwise
            continue
        req_match = re.match(r"\s*required:\s*(true|false)", line)
        if req_match and current is not None:
            slots[current] = req_match.group(1) == "true"
    return slots


# --------------------------------------------------------------------------- #
# Expected content (what a fresh stamp would produce today)
# --------------------------------------------------------------------------- #
def _iter_current_templates():
    """Yield (source_path, relative_path) for every current template file.

    Mirrors the render engine's tree walk (skipping the ``slots.yml`` metadata at the
    tree root via render's public ``MANIFEST_FILENAMES``) so this script sees exactly
    the same template set stamp.py renders.
    """
    for root, _dirs, files in os.walk(TEMPLATES_DIR):
        for name in sorted(files):
            src = Path(root) / name
            rel = src.relative_to(TEMPLATES_DIR)
            if rel.parent == Path(".") and name in render.MANIFEST_FILENAMES:
                continue
            yield src, rel


def _build_expected(slots: dict) -> dict:
    """Return ``{template-relative-path: expected text}`` for every current template.

    Each template is rendered with the *recorded* slots via ``render.substitute``
    (which leaves unknown ``{{KEY}}`` intact rather than raising — a template added
    since the stamp that needs a not-yet-recorded slot then surfaces as a leftover
    placeholder instead of aborting the whole comparison). The dangling-connectivity
    strip is delegated to stamp so the expected text matches a fresh stamp exactly.
    """
    with tempfile.TemporaryDirectory(prefix="cmw-sync-expected-") as tmp:
        stage = Path(tmp)
        expected = {}
        for src, rel in _iter_current_templates():
            text = render.substitute(src.read_text(encoding="utf-8"), slots)
            dst = stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
            expected[rel.as_posix()] = text

        # Reuse stamp's exact post-render step for the two connectivity files so an
        # empty CONNECTIVITY_CMD is handled identically here and at stamp time.
        stamp.strip_dangling_connectivity(stage, slots)
        for name in stamp.CONNECTIVITY_FILES:
            staged = stage / name
            if staged.is_file():
                expected[name] = staged.read_text(encoding="utf-8")
    return expected


def _sha256_text(text: str) -> str:
    """Lowercase hex SHA-256 of *text* encoded as UTF-8 (matches stamp's file hash)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _template_rel(template: str) -> str:
    """Strip the ``templates/`` prefix a manifest entry records for its source."""
    return template[len(TEMPLATE_PREFIX):] if template.startswith(TEMPLATE_PREFIX) else template


def _version_tuple(version: str) -> tuple:
    """Numeric ``(major, minor, patch, ...)`` core of a semver string for comparison."""
    core = version.split("+")[0].split("-")[0]
    return tuple(int(part) for part in core.split(".") if part.isdigit())


# --------------------------------------------------------------------------- #
# Analysis (pure — inspects, never writes)
# --------------------------------------------------------------------------- #
def _classify_file(entry: dict, target: Path, expected: dict) -> dict:
    """Classify one recorded file against its current template and on-disk state."""
    path = entry["path"]
    template = entry["template"]
    recorded_sha = entry["sha256"]
    rel = _template_rel(template)
    exp = expected.get(rel)

    finding = {"path": path, "template": template, "unfillable": False}

    if exp is None:
        # The source template no longer exists in the plugin — the stamped file is
        # obsolete governance. We report it but never delete it.
        finding["status"] = OBSOLETE
        return finding

    finding["unfillable"] = "{{" in exp  # a new slot leaked in; cannot be re-rendered clean
    disk = target / path
    if not disk.is_file():
        finding["status"] = MISSING
        return finding

    disk_sha = stamp.sha256_file(disk)
    expected_sha = _sha256_text(exp)

    # If the on-disk content already equals the current render, the file is in sync
    # regardless of the recorded hash — e.g. a user who hand-edited it to exactly the
    # plugin's new content should not see a phantom conflict.
    if disk_sha == expected_sha:
        finding["status"] = IN_SYNC
        return finding

    local_edit = disk_sha != recorded_sha       # on-disk differs from what we stamped
    template_changed = expected_sha != recorded_sha  # the template moved on since the stamp

    if not local_edit and not template_changed:
        finding["status"] = IN_SYNC
    elif not local_edit and template_changed:
        finding["status"] = BEHIND
    elif local_edit and not template_changed:
        finding["status"] = LOCAL_MOD
    else:
        finding["status"] = CONFLICT
    return finding


def analyze(target: Path, manifest: dict, expected: dict, installed_version: str) -> dict:
    """Compare a stamped repo against the plugin's current templates + slots + version."""
    files = []
    covered_templates = set()
    for entry in manifest.get("files", []):
        files.append(_classify_file(entry, target, expected))
        covered_templates.add(_template_rel(entry["template"]))

    new_templates = [
        rel.as_posix()
        for _src, rel in _iter_current_templates()
        if rel.as_posix() not in covered_templates
    ]

    recorded_slots = manifest.get("slots", {}) or {}
    current = _current_slots()  # {key: required?}
    slots = {
        "new": [k for k in current if k not in recorded_slots],
        # Only a REQUIRED slot left empty is "unfilled"; an empty optional slot (e.g.
        # a blank CONNECTIVITY_CMD) is a legitimate stamp, not drift.
        "unfilled": [
            k
            for k, required in current.items()
            if required and k in recorded_slots and not str(recorded_slots[k]).strip()
        ],
        "stale": [k for k in recorded_slots if k not in current],
    }

    baseline_version = str(manifest.get("pluginVersion", "0.0.0"))
    version_behind = _version_tuple(baseline_version) < _version_tuple(installed_version)

    return {
        "target": str(target),
        "installed_version": installed_version,
        "baseline_version": baseline_version,
        "version_behind": version_behind,
        "files": files,
        "new_templates": new_templates,
        "slots": slots,
    }


def _has_drift(report: dict) -> bool:
    """True if the repo diverges from the plugin in any category."""
    if report["version_behind"] or report["new_templates"]:
        return True
    slots = report["slots"]
    if slots["new"] or slots["unfilled"] or slots["stale"]:
        return True
    return any(f["status"] != IN_SYNC for f in report["files"])


# --------------------------------------------------------------------------- #
# Apply (approval-gated writes — protects user edits)
# --------------------------------------------------------------------------- #
def _write_expected(target: Path, dest_path: str, source_rel: str, text: str) -> str:
    """Write expected *text* to ``target/<dest_path>`` and return its SHA-256.

    ``dest_path`` is the on-disk destination (the manifest-recorded ``path`` for an
    existing file, or the stamp-derived location for a new one). ``source_rel`` is the
    template-relative path used only to locate the SOURCE template whose mode
    (executable bits for git hooks / ``*.sh``) is carried over — the destination and
    the source can differ (the PR template and nested-mode CLAUDE.md are relocated),
    which is exactly the bug this separation fixes.
    """
    dst = target / dest_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    src = TEMPLATES_DIR / source_rel
    if src.is_file():
        shutil.copymode(src, dst)
    return stamp.sha256_file(dst)


def _infer_mode(manifest: dict):
    """Recover the (mode, subdir) a repo was stamped with from its manifest.

    Only CLAUDE.md moves in nested mode, and it is always recorded, so its recorded
    ``path`` reveals whether the stamp was root or nested. This lets a new template be
    placed exactly where a fresh stamp of the same repo would put it.
    """
    for entry in manifest.get("files", []):
        if entry.get("template") == TEMPLATE_PREFIX + "CLAUDE.md":
            path = entry["path"]
            if path.endswith("/CLAUDE.md") and path != "CLAUDE.md":
                return "nested", path[: -len("/CLAUDE.md")]
            break
    return "root", None


def _new_template_destination(target: Path, manifest: dict, rel: str) -> str:
    """Destination path for a template not yet in the manifest.

    Delegates to stamp's placement logic so a newly-added relocated file (the PR
    template, nested-mode CLAUDE.md) lands where a stamp would put it rather than at
    its raw tree-relative path — the placement rules are not duplicated here.
    """
    mode, subdir = _infer_mode(manifest)
    dest = stamp.target_relpath(
        Path(rel), mode, subdir, target, stamp.prior_owns_primary(manifest)
    )
    return dest.as_posix()


def apply_changes(
    target: Path, report: dict, expected: dict, manifest: dict, installed_version: str, force: bool
) -> dict:
    """Repair the safe drift categories and refresh the manifest. Returns a summary.

    ``behind`` files are re-rendered and rewritten; ``missing`` files are restored;
    ``new`` templates are stamped in. ``local-modification`` / ``conflict`` files are
    **skipped** (their edits preserved) unless ``force`` is set. A file whose expected
    render still holds ``{{...}}`` (a new, unfilled slot) is never written — it is
    reported as needing a re-init instead.
    """
    entries_by_path = {e["path"]: e for e in manifest["files"]}
    updated, restored, forced, added, skipped, unfillable = [], [], [], [], [], []

    for finding in report["files"]:
        path = finding["path"]
        rel = _template_rel(finding["template"])
        exp = expected.get(rel)
        status = finding["status"]

        if status in (IN_SYNC, OBSOLETE):
            continue
        if finding["unfillable"]:  # applies to any status carrying a leftover placeholder
            unfillable.append(path)
            continue

        # Write to the RECORDED destination (path), not the template-relative rel:
        # relocated files (PR template, nested CLAUDE.md) have path != rel.
        if status == BEHIND:
            entries_by_path[path]["sha256"] = _write_expected(target, path, rel, exp)
            updated.append(path)
        elif status == MISSING:
            entries_by_path[path]["sha256"] = _write_expected(target, path, rel, exp)
            restored.append(path)
        elif status in (LOCAL_MOD, CONFLICT):
            if force:
                entries_by_path[path]["sha256"] = _write_expected(target, path, rel, exp)
                forced.append(path)
            else:
                skipped.append(path)

    new_entries = []
    for rel in report["new_templates"]:
        exp = expected.get(rel)
        if exp is None or "{{" in exp:
            unfillable.append(rel)
            continue
        dest = _new_template_destination(target, manifest, rel)
        sha = _write_expected(target, dest, rel, exp)
        new_entries.append({"path": dest, "template": TEMPLATE_PREFIX + rel, "sha256": sha})
        added.append(dest)

    wrote_files = bool(updated or restored or forced or added)
    if wrote_files or report["version_behind"]:
        manifest["pluginVersion"] = installed_version
        manifest["templateSetVersion"] = installed_version
        manifest["stampedAt"] = stamp.now_iso_utc()
        merged = list(entries_by_path.values()) + new_entries
        manifest["files"] = sorted(merged, key=lambda e: e["path"])
        (target / BASELINE_RELPATH).write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        manifest_refreshed = True
    else:
        manifest_refreshed = False

    return {
        "updated": updated,
        "restored": restored,
        "forced": forced,
        "added": added,
        "skipped": skipped,
        "unfillable": unfillable,
        "manifest_refreshed": manifest_refreshed,
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _print_bucket(label: str, findings: list) -> None:
    if not findings:
        return
    print(f"  {label} ({len(findings)}):")
    for finding in findings:
        print(f"    {finding['path']}")


def print_report(report: dict) -> None:
    """Print the human-facing, categorized drift report (report-only mode)."""
    print(f"Baseline drift report — {report['target']}")
    print(f"  plugin installed : {PLUGIN_NAME} v{report['installed_version']}")
    tag = "BEHIND plugin — stamp trails installed version" if report["version_behind"] else "current"
    print(f"  baseline stamped : v{report['baseline_version']}  [{tag}]")

    buckets = defaultdict(list)
    for finding in report["files"]:
        buckets[finding["status"]].append(finding)

    print()
    print(f"Files ({len(report['files'])} recorded):")
    print(f"  in sync ({len(buckets[IN_SYNC])})")
    _print_bucket("behind — plugin template updated (safe to update)", buckets[BEHIND])
    _print_bucket("locally modified — your edits (preserved unless --force)", buckets[LOCAL_MOD])
    _print_bucket("CONFLICT — you edited AND the template changed (manual merge)", buckets[CONFLICT])
    _print_bucket("missing — recorded file not on disk", buckets[MISSING])
    _print_bucket("obsolete — template removed from the plugin", buckets[OBSOLETE])

    unfillable = [f["path"] for f in report["files"] if f["unfillable"]]
    if unfillable:
        print(f"  needs re-init — new slot unfilled, cannot re-render clean ({len(unfillable)}):")
        for path in unfillable:
            print(f"    {path}")

    if report["new_templates"]:
        print()
        print(f"New templates — added to the plugin since the stamp ({len(report['new_templates'])}):")
        for rel in report["new_templates"]:
            print(f"    {rel}")

    slots = report["slots"]
    if slots["new"] or slots["unfilled"] or slots["stale"]:
        print()
        print("Slots:")
        if slots["new"]:
            print(f"    new (plugin added — re-run init-repo to fill): {', '.join(slots['new'])}")
        if slots["unfilled"]:
            print(f"    unfilled (empty value recorded): {', '.join(slots['unfilled'])}")
        if slots["stale"]:
            print(f"    stale (recorded but no longer defined — renamed/removed): {', '.join(slots['stale'])}")

    print()
    if _has_drift(report):
        print("Summary: DRIFT DETECTED — re-run with --apply to update (approval-gated).")
    else:
        print("Summary: in sync with the plugin. Nothing to do.")


def print_apply(report: dict, summary: dict, force: bool) -> None:
    """Print what an ``--apply`` run changed and what it deliberately left alone."""
    print(f"Applied baseline update — {report['target']}")
    if summary["manifest_refreshed"]:
        old, new = report["baseline_version"], report["installed_version"]
        arrow = f"v{old} -> v{new}" if old != new else f"v{new} (unchanged)"
        print(f"  plugin version : {arrow}")

    for label, key in (
        ("updated (behind)", "updated"),
        ("restored (missing)", "restored"),
        ("added (new template)", "added"),
        ("overwritten (--force)", "forced"),
    ):
        if summary[key]:
            print(f"  {label} ({len(summary[key])}):")
            for path in summary[key]:
                print(f"    {path}")

    if summary["skipped"]:
        print(f"  SKIPPED — local edits preserved, NOT overwritten ({len(summary['skipped'])}):")
        for path in summary["skipped"]:
            print(f"    {path}")
        print("    re-run with --force to overwrite these (your edits will be lost).")

    if summary["unfillable"]:
        print(f"  needs re-init — new slot unfilled, cannot re-render clean ({len(summary['unfillable'])}):")
        for path in summary["unfillable"]:
            print(f"    {path}")

    if summary["manifest_refreshed"]:
        print(f"  baseline manifest refreshed: {BASELINE_RELPATH.as_posix()}")
    else:
        print("  nothing to apply — already in sync.")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _analyze_target(target: Path):
    """Load inputs and analyze *target*. Returns (report, expected, manifest, version)."""
    installed_version = _read_installed_version()
    manifest = _read_manifest(target)
    slots = manifest.get("slots", {}) or {}
    expected = _build_expected(slots)
    report = analyze(target, manifest, expected, installed_version)
    return report, expected, manifest, installed_version


def run(target: Path, apply: bool, force: bool) -> int:
    """Report drift (and optionally repair it). Returns a process exit code."""
    report, expected, manifest, installed_version = _analyze_target(target)

    if apply:
        summary = apply_changes(target, report, expected, manifest, installed_version, force)
        print_apply(report, summary, force)
        # Residual drift after apply: files we deliberately left alone (edits /
        # unfillable) AND slot drift the user must resolve via re-init (a plugin-added
        # or unfilled slot). Stale slots are cosmetic, so they do not count.
        slots = report["slots"]
        remaining = bool(
            summary["skipped"] or summary["unfillable"] or slots["new"] or slots["unfilled"]
        )
        return EXIT_DRIFT if remaining else EXIT_OK

    print_report(report)
    return EXIT_DRIFT if _has_drift(report) else EXIT_OK


# --------------------------------------------------------------------------- #
# Self-test (no network; drives the full flow against temp repos)
# --------------------------------------------------------------------------- #
def _assert(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        raise SystemExit(1)


def _fresh_stamp(target: Path, version: str) -> dict:
    """Stamp the bundled sample slots into *target* (reusing stamp.py). Returns slots."""
    slots = render.load_slots(stamp.SAMPLE_SLOTS_PATH)
    result = stamp.run_stamp(
        slots, target, mode="root", subdir=None, dry_run=False, force=False, version=version
    )
    _assert(not result["problems"], f"fresh stamp had problems: {result['problems']}")
    return slots


def _finding(report: dict, path: str) -> dict:
    for finding in report["files"]:
        if finding["path"] == path:
            return finding
    raise AssertionError(f"no finding recorded for {path}")


def _load_manifest_file(target: Path) -> dict:
    return json.loads((target / BASELINE_RELPATH).read_text(encoding="utf-8"))


def _write_manifest_file(target: Path, manifest: dict) -> None:
    (target / BASELINE_RELPATH).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def _case_template_drift_and_version(installed: str) -> None:
    """(a) clean stamp is in sync; (b) template drift -> behind + --apply repairs;
    (d) a version-behind manifest is reported and bumped by --apply."""
    with tempfile.TemporaryDirectory(prefix="cmw-sync-selftest-drift-") as tmp:
        target = Path(tmp)
        _fresh_stamp(target, installed)

        # (a) a fresh stamp with the installed version is fully in sync.
        report, *_ = _analyze_target(target)
        _assert(not _has_drift(report), f"fresh stamp reported drift: {report}")

        # (b) + (d) simulate template drift on one file AND an older plugin version.
        drift_path = ".claude/rules/ticketing.md"
        manifest = _load_manifest_file(target)
        entry = next(e for e in manifest["files"] if e["path"] == drift_path)
        on_disk = target / drift_path
        older_variant = on_disk.read_text(encoding="utf-8") + "\n<!-- OLD VARIANT (pre-drift) -->\n"
        on_disk.write_text(older_variant, encoding="utf-8")
        entry["sha256"] = hashlib.sha256(older_variant.encode("utf-8")).hexdigest()
        manifest["pluginVersion"] = "0.0.1"
        _write_manifest_file(target, manifest)

        report, expected, manifest, version = _analyze_target(target)
        _assert(_finding(report, drift_path)["status"] == BEHIND, "template drift not classified as behind")
        _assert(report["version_behind"], "version-behind manifest not reported")

        summary = apply_changes(target, report, expected, manifest, version, force=False)
        _assert(drift_path in summary["updated"], "behind file was not updated by --apply")

        refreshed = _load_manifest_file(target)
        _assert(refreshed["pluginVersion"] == installed, "--apply did not bump pluginVersion")
        _assert("OLD VARIANT" not in on_disk.read_text(encoding="utf-8"), "behind file not re-rendered")
        new_entry = next(e for e in refreshed["files"] if e["path"] == drift_path)
        _assert(
            new_entry["sha256"] == _sha256_text(expected[drift_path]),
            "manifest sha not updated to the re-rendered content",
        )

        report_after, *_ = _analyze_target(target)
        _assert(not _has_drift(report_after), "drift remained after --apply")


def _case_local_edit(installed: str) -> None:
    """(c) a hand-edited file is a local-modification, preserved by --apply,
    overwritten only with --force."""
    with tempfile.TemporaryDirectory(prefix="cmw-sync-selftest-local-") as tmp:
        target = Path(tmp)
        _fresh_stamp(target, installed)

        edit_path = ".claude/rules/approvals.md"
        on_disk = target / edit_path
        edited = on_disk.read_text(encoding="utf-8") + "\n<!-- LOCAL EDIT -->\n"
        on_disk.write_text(edited, encoding="utf-8")  # manifest sha left untouched

        report, expected, manifest, version = _analyze_target(target)
        _assert(_finding(report, edit_path)["status"] == LOCAL_MOD, "local edit not classified as local-modification")

        summary = apply_changes(target, report, expected, manifest, version, force=False)
        _assert("LOCAL EDIT" in on_disk.read_text(encoding="utf-8"), "local edit was clobbered by --apply")
        _assert(edit_path in summary["skipped"], "local edit not reported as skipped")

        report, expected, manifest, version = _analyze_target(target)
        forced = apply_changes(target, report, expected, manifest, version, force=True)
        _assert(edit_path in forced["forced"], "--force did not overwrite the local edit")
        _assert("LOCAL EDIT" not in on_disk.read_text(encoding="utf-8"), "--force left the local edit in place")


def _case_slot_drift(installed: str) -> None:
    """Slot drift: a plugin-added key, a stale key, and an unfilled value are reported."""
    with tempfile.TemporaryDirectory(prefix="cmw-sync-selftest-slots-") as tmp:
        target = Path(tmp)
        _fresh_stamp(target, installed)

        manifest = _load_manifest_file(target)
        manifest["slots"].pop("LINEAR_TEAM", None)   # defined by slots.yml but not recorded -> new
        manifest["slots"]["OLD_RENAMED_SLOT"] = "x"  # recorded but not defined -> stale
        manifest["slots"]["BUILD_CMD"] = ""          # required slot left empty -> unfilled
        manifest["slots"]["DEFAULT_PROJECT"] = ""    # optional slot empty -> NOT unfilled
        _write_manifest_file(target, manifest)

        report, *_ = _analyze_target(target)
        _assert("LINEAR_TEAM" in report["slots"]["new"], "plugin-added slot not reported as new")
        _assert("OLD_RENAMED_SLOT" in report["slots"]["stale"], "stale slot not reported")
        _assert("BUILD_CMD" in report["slots"]["unfilled"], "empty required slot not reported as unfilled")
        _assert(
            "DEFAULT_PROJECT" not in report["slots"]["unfilled"],
            "empty optional slot wrongly reported as unfilled",
        )


def _case_new_template(installed: str) -> None:
    """A template absent from the manifest is a new template, stamped in by --apply."""
    with tempfile.TemporaryDirectory(prefix="cmw-sync-selftest-new-") as tmp:
        target = Path(tmp)
        _fresh_stamp(target, installed)

        new_tpl = ".claude/rules/mcp-security.md"
        manifest = _load_manifest_file(target)
        manifest["files"] = [e for e in manifest["files"] if e["path"] != new_tpl]
        _write_manifest_file(target, manifest)

        report, expected, manifest, version = _analyze_target(target)
        _assert(new_tpl in report["new_templates"], "uncovered template not reported as new")

        summary = apply_changes(target, report, expected, manifest, version, force=False)
        _assert(new_tpl in summary["added"], "new template not stamped in by --apply")
        refreshed = _load_manifest_file(target)
        _assert(
            any(e["path"] == new_tpl for e in refreshed["files"]),
            "new template not recorded in the refreshed manifest",
        )


def _case_relocated_pr_template(installed: str) -> None:
    """Relocated file (path != rel): a BEHIND or MISSING PR template is written to its
    recorded ``.github/`` destination — never the repo root — and the manifest sha
    tracks the real file so a second run does not misread it as a local edit."""
    pr_path = ".github/pull_request_template.md"
    stray = "pull_request_template.md"  # where the old rel-as-destination bug would write

    # --- behind ---
    with tempfile.TemporaryDirectory(prefix="cmw-sync-selftest-pr-behind-") as tmp:
        target = Path(tmp)
        _fresh_stamp(target, installed)
        on_disk = target / pr_path
        _assert(on_disk.is_file(), "fresh stamp did not write the PR template under .github/")

        manifest = _load_manifest_file(target)
        entry = next(e for e in manifest["files"] if e["path"] == pr_path)
        older = on_disk.read_text(encoding="utf-8") + "\n<!-- OLD PR VARIANT -->\n"
        on_disk.write_text(older, encoding="utf-8")
        entry["sha256"] = hashlib.sha256(older.encode("utf-8")).hexdigest()
        _write_manifest_file(target, manifest)

        report, expected, manifest, version = _analyze_target(target)
        _assert(_finding(report, pr_path)["status"] == BEHIND, "behind PR template not classified as behind")

        summary = apply_changes(target, report, expected, manifest, version, force=False)
        _assert(pr_path in summary["updated"], "behind PR template not updated")
        _assert(not (target / stray).exists(), "PR template written to repo root instead of .github/")
        _assert("OLD PR VARIANT" not in on_disk.read_text(encoding="utf-8"), "real .github/ PR template not updated")
        refreshed = _load_manifest_file(target)
        new_entry = next(e for e in refreshed["files"] if e["path"] == pr_path)
        _assert(new_entry["sha256"] == stamp.sha256_file(on_disk), "manifest sha does not match the real .github/ file")
        report_after, *_ = _analyze_target(target)
        _assert(
            _finding(report_after, pr_path)["status"] == IN_SYNC,
            "second run misclassified the relocated PR template (false local-modification)",
        )

    # --- missing restore ---
    with tempfile.TemporaryDirectory(prefix="cmw-sync-selftest-pr-missing-") as tmp:
        target = Path(tmp)
        _fresh_stamp(target, installed)
        on_disk = target / pr_path
        on_disk.unlink()

        report, expected, manifest, version = _analyze_target(target)
        _assert(_finding(report, pr_path)["status"] == MISSING, "deleted PR template not classified as missing")

        summary = apply_changes(target, report, expected, manifest, version, force=False)
        _assert(pr_path in summary["restored"], "PR template not restored")
        _assert(not (target / stray).exists(), "restored PR template landed at repo root")
        _assert(on_disk.is_file(), "PR template not restored under .github/")
        refreshed = _load_manifest_file(target)
        new_entry = next(e for e in refreshed["files"] if e["path"] == pr_path)
        _assert(new_entry["sha256"] == stamp.sha256_file(on_disk), "restored manifest sha does not match the real file")
        report_after, *_ = _analyze_target(target)
        _assert(not _has_drift(report_after), "drift remained after restoring the PR template")


def _case_connectivity_strip_lockstep(installed: str) -> None:
    """The dangling-connectivity strip runs inside sync's expected-builder: a stamp
    with an empty CONNECTIVITY_CMD reads as in sync (no false 'behind'), and a drifted
    CLAUDE.md is re-rendered with the connectivity line stripped."""
    with tempfile.TemporaryDirectory(prefix="cmw-sync-selftest-conn-") as tmp:
        target = Path(tmp)
        slots = dict(render.load_slots(stamp.SAMPLE_SLOTS_PATH))
        slots["CONNECTIVITY_CMD"] = ""
        result = stamp.run_stamp(
            slots, target, mode="root", subdir=None, dry_run=False, force=False, version=installed
        )
        _assert(not result["problems"], f"empty-connectivity stamp had problems: {result['problems']}")

        # If the strip were NOT applied in the expected-builder, expected CLAUDE.md /
        # README would keep the dangling line and mismatch the stamped files -> drift.
        report, *_ = _analyze_target(target)
        _assert(not _has_drift(report), "empty-connectivity stamp falsely flagged drift (strip not in expected-builder)")

        claude_path = "CLAUDE.md"
        manifest = _load_manifest_file(target)
        entry = next(e for e in manifest["files"] if e["path"] == claude_path)
        on_disk = target / claude_path
        older = on_disk.read_text(encoding="utf-8") + "\n<!-- OLD CLAUDE VARIANT -->\n"
        on_disk.write_text(older, encoding="utf-8")
        entry["sha256"] = hashlib.sha256(older.encode("utf-8")).hexdigest()
        _write_manifest_file(target, manifest)

        report, expected, manifest, version = _analyze_target(target)
        _assert(_finding(report, claude_path)["status"] == BEHIND, "drifted CLAUDE.md not classified as behind")
        apply_changes(target, report, expected, manifest, version, force=False)
        text = on_disk.read_text(encoding="utf-8")
        _assert("OLD CLAUDE VARIANT" not in text, "CLAUDE.md was not re-rendered")
        _assert(
            "verify external connectivity" not in text,
            "re-rendered CLAUDE.md kept the dangling connectivity line (strip not applied)",
        )
        report_after, *_ = _analyze_target(target)
        _assert(_finding(report_after, claude_path)["status"] == IN_SYNC, "CLAUDE.md not in sync after apply")


def run_self_test() -> int:
    """Drive template drift, local edits, slot drift, a new template, and version-behind."""
    installed = _read_installed_version()
    _case_template_drift_and_version(installed)
    _case_local_edit(installed)
    _case_slot_drift(installed)
    _case_new_template(installed)
    _case_relocated_pr_template(installed)
    _case_connectivity_strip_lockstep(installed)

    print("PASS: crow-mind-workflow sync-baseline reconciles drift correctly")
    print(f"  plugin version               : {installed}")
    print("  clean stamp                  : reported in sync")
    print("  template drift               : classified 'behind' -> --apply re-rendered it")
    print("  version-behind manifest      : reported -> --apply bumped it")
    print("  local edit                   : classified 'local-modification' -> preserved (no --force)")
    print("  local edit + --force         : overwritten")
    print("  slot drift                   : new / stale / unfilled all reported")
    print("  new template                 : reported -> --apply stamped it in")
    print("  relocated PR template        : behind/missing written to .github/, not repo root")
    print("  connectivity-strip lockstep  : empty CONNECTIVITY_CMD in sync; drift re-render stripped")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report (and optionally repair) drift between a stamped repo and the plugin.",
    )
    parser.add_argument("--target", type=Path, help="stamped repo directory to check")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write updates for drifted/new files and refresh the manifest (approval-gated)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --apply, also overwrite locally-modified / conflicting files (loses edits)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="drive the full flow against temp repos and verify (no network)",
    )
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.target:
        parser.error("--target is required (or use --self-test)")
    if args.force and not args.apply:
        parser.error("--force only applies with --apply")

    try:
        return run(args.target, apply=args.apply, force=args.force)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
