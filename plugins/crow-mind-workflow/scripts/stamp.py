#!/usr/bin/env python3
"""Stamp a target repo with the rendered crow-mind-workflow governance baseline.

``render.py`` is the substitution primitive; this script is the *placement* layer
on top of it. It renders ``templates/`` with a set of slot values (reusing
``render.render_tree`` — substitution is never reimplemented here), lays the
rendered files into the right spots in a target repo, and records exactly what was
stamped in a baseline manifest so the sync-baseline skill can detect drift later.

CLI
---
::

    stamp.py --slots <values.json> --target <repo-dir>
             [--mode root|nested] [--subdir <path>] [--dry-run] [--force]

Placement rules (see the init-repo skill for the human-facing procedure)::

    CLAUDE.md               -> <target>/CLAUDE.md            (root mode)
                               <target>/<subdir>/CLAUDE.md   (nested mode)
    .claude/**              -> <target>/.claude/**           (always repo root)
    .githooks/**            -> <target>/.githooks/**         (exec bits preserved)
    README-governance.md    -> <target>/README-governance.md (never clobbers README.md)
    pull_request_template.md-> <target>/.github/pull_request_template.md
                               ...or .crow-mind.md if one already exists (no clobber)

The baseline manifest is written to ``<target>/.claude/.workflow-baseline.json`` and
conforms to ``baseline-manifest.schema.json``.

Two carry-forward behaviors from the S2 review:
  * PR-template collision — write ``pull_request_template.crow-mind.md`` instead of
    overwriting a repo's own template.
  * Empty ``CONNECTIVITY_CMD`` — strip the now-dangling "verify connectivity"
    comment line from the rendered CLAUDE.md / README-governance.md so no orphan
    comment is left behind.

Self-test (proves an end-to-end stamp is coherent)::

    stamp.py --self-test

Exits non-zero on the first failed assertion; prints a PASS summary otherwise.
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
from datetime import datetime, timezone
from pathlib import Path

# Reuse the shared render engine (never reimplement substitution). render.py
# resolves its own paths from __file__, so importing it is CWD-independent.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import render  # noqa: E402

PLUGIN_DIR = SCRIPT_DIR.parent
TEMPLATES_DIR = PLUGIN_DIR / "templates"
SCHEMA_PATH = PLUGIN_DIR / "baseline-manifest.schema.json"
PLUGIN_JSON_PATH = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
SAMPLE_SLOTS_PATH = SCRIPT_DIR / "sample-slots.json"

PLUGIN_NAME = "crow-mind-workflow"
BASELINE_RELPATH = Path(".claude") / ".workflow-baseline.json"

# The optional CONNECTIVITY_CMD slot appears in these rendered files; when it is
# empty its comment line is dangling and must be removed.
CONNECTIVITY_FILES = ("CLAUDE.md", "README-governance.md")
CONNECTIVITY_TOKEN = "{{CONNECTIVITY_CMD}}"

# Where the collision-safe PR template lands when the repo already ships one.
PR_TEMPLATE_SOURCE = Path("templates") / "pull_request_template.md"
PR_TEMPLATE_PRIMARY = Path(".github") / "pull_request_template.md"
PR_TEMPLATE_FALLBACK = Path(".github") / "pull_request_template.crow-mind.md"


class StampError(Exception):
    """Raised when a stamp cannot proceed (bad args, refusal, render failure)."""


# --------------------------------------------------------------------------- #
# Plugin metadata
# --------------------------------------------------------------------------- #
def _read_plugin_version() -> str:
    """Return the ``version`` recorded in the plugin manifest."""
    data = json.loads(PLUGIN_JSON_PATH.read_text(encoding="utf-8"))
    version = data.get("version")
    if not version:
        raise StampError(f"no version in {PLUGIN_JSON_PATH}")
    return str(version)


def now_iso_utc() -> str:
    """Current time as an ISO-8601 UTC timestamp (e.g. 2026-07-24T18:03:11Z).

    Public: sync-baseline restamps ``stampedAt`` with this on ``--apply``, so it is
    a supported entry point of the shared stamping toolkit.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Rendering + placement
# --------------------------------------------------------------------------- #
def strip_dangling_connectivity(stage_dir: Path, slots: dict) -> bool:
    """Drop the connectivity comment line when ``CONNECTIVITY_CMD`` is empty.

    Works line-for-line: the source lines carrying ``{{CONNECTIVITY_CMD}}`` are
    rendered with the *same* slots (via ``render.substitute``) to get their exact
    rendered text, then those lines are removed from the staged output. Reusing the
    render primitive keeps this in lockstep with whole-file rendering. Returns True
    if any line was removed.

    Public: sync-baseline's expected-content builder calls this so its notion of a
    stamped file is byte-for-byte identical to a real stamp — the strip lives in
    exactly one place.
    """
    if slots.get("CONNECTIVITY_CMD", "").strip():
        return False  # a real command was supplied — keep the line

    removed = False
    for name in CONNECTIVITY_FILES:
        template = TEMPLATES_DIR / name
        staged = stage_dir / name
        if not template.is_file() or not staged.is_file():
            continue

        # Only queue lines that still hold visible content once rendered. A bare
        # ``{{CONNECTIVITY_CMD}}`` line renders to ""; queuing that would match —
        # and delete — every blank line in the file.
        drop = set()
        for line in template.read_text(encoding="utf-8").splitlines():
            if CONNECTIVITY_TOKEN not in line:
                continue
            rendered = render.substitute(line, slots)
            if rendered.strip():
                drop.add(rendered)
        if not drop:
            continue

        kept = [
            line
            for line in staged.read_text(encoding="utf-8").splitlines(keepends=True)
            if line.rstrip("\r\n") not in drop
        ]
        staged.write_text("".join(kept), encoding="utf-8")
        removed = True
    return removed


def prior_owns_primary(prior_manifest) -> bool:
    """True if a prior baseline recorded the primary PR template as *ours*.

    Distinguishes "our own previously-stamped template sitting at the primary path"
    (safe to overwrite in place on a ``--force`` re-stamp) from a genuinely FOREIGN
    template the repo already shipped (which we must not clobber).

    Public: sync-baseline reuses this (with :func:`target_relpath`) to place a
    newly-added template at the same destination a stamp would choose.
    """
    if not prior_manifest:
        return False
    primary = PR_TEMPLATE_PRIMARY.as_posix()
    source = PR_TEMPLATE_SOURCE.as_posix()
    return any(
        f.get("path") == primary and f.get("template") == source
        for f in prior_manifest.get("files", [])
    )


def target_relpath(
    rel: Path, mode: str, subdir: str, probe_root: Path, prior_owns_primary: bool
) -> Path:
    """Map a rendered relative path to its destination relative to the target.

    ``probe_root`` is inspected (not written) to resolve the PR-template collision;
    ``prior_owns_primary`` says whether an existing primary template is one we
    stamped before (overwrite in place) rather than the repo's own (divert).

    Public: sync-baseline routes a newly-added template through this so relocated
    files (the PR template, nested-mode CLAUDE.md) land where a stamp would put
    them — placement logic is not duplicated in the sync tool.
    """
    if rel == Path("CLAUDE.md"):
        return (Path(subdir) / "CLAUDE.md") if mode == "nested" else Path("CLAUDE.md")
    if rel == Path("README-governance.md"):
        return Path("README-governance.md")
    if rel == Path("pull_request_template.md"):
        foreign_primary = (probe_root / PR_TEMPLATE_PRIMARY).exists() and not prior_owns_primary
        return PR_TEMPLATE_FALLBACK if foreign_primary else PR_TEMPLATE_PRIMARY
    # .claude/** and .githooks/** keep their layout at the repo root.
    return rel


def sha256_file(path: Path) -> str:
    """Lowercase hex SHA-256 of a file's bytes.

    Public: sync-baseline hashes on-disk files with this to compare against manifest
    hashes, so both tools hash identically.
    """
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


# Back-compat aliases: these members were underscore-private before sync-baseline
# reused them. They are now the shared stamping toolkit's supported (public) surface;
# the underscore names remain so any earlier caller keeps working.
_now_iso_utc = now_iso_utc
_strip_dangling_connectivity = strip_dangling_connectivity
_prior_owns_primary = prior_owns_primary
_target_relpath = target_relpath
_sha256_file = sha256_file


def _place(
    slots: dict,
    write_root: Path,
    probe_root: Path,
    mode: str,
    subdir: str,
    prior_owns_primary: bool = False,
):
    """Render + lay templates under ``write_root``; return (entries, notes).

    ``entries`` is the manifest ``files`` array (target-relative path, source
    template path, sha256 of the written file). ``notes`` records human-facing
    decisions (PR collision, connectivity omission).
    """
    with tempfile.TemporaryDirectory(prefix="cmw-stage-") as stage:
        stage_dir = Path(stage)
        try:
            rendered = render.render_tree(slots, TEMPLATES_DIR, stage_dir)
        except render.RenderError as exc:
            raise StampError(str(exc)) from exc

        connectivity_omitted = strip_dangling_connectivity(stage_dir, slots)

        entries = []
        pr_collision = False
        for rel_str in rendered:
            rel = Path(rel_str)
            dest_rel = target_relpath(rel, mode, subdir, probe_root, prior_owns_primary)
            if dest_rel == PR_TEMPLATE_FALLBACK:
                pr_collision = True

            src = stage_dir / rel
            dst = write_root / dest_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)  # preserves mode -> git-hook exec bits survive

            entries.append(
                {
                    "path": dest_rel.as_posix(),
                    "template": (Path("templates") / rel).as_posix(),
                    "sha256": sha256_file(dst),
                }
            )

    entries.sort(key=lambda e: e["path"])
    notes = {
        "pr_template_collision": pr_collision,
        "connectivity_omitted": connectivity_omitted,
    }
    return entries, notes


def _build_manifest(slots: dict, entries: list, version: str, stamped_at: str) -> dict:
    """Assemble the baseline manifest object."""
    return {
        "pluginName": PLUGIN_NAME,
        "pluginVersion": version,
        # Deliberately coupled to pluginVersion until the template set gains its own
        # version; the schema permits them to diverge once that day comes.
        "templateSetVersion": version,
        "stampedAt": stamped_at,
        "slots": {k: str(v) for k, v in slots.items()},
        "files": entries,
    }


def _write_baseline(write_root: Path, manifest: dict) -> Path:
    """Write the baseline manifest under ``write_root`` and return its path."""
    dst = write_root / BASELINE_RELPATH
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return dst


# --------------------------------------------------------------------------- #
# Verification (shared by --self-test and --dry-run)
# --------------------------------------------------------------------------- #
def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_manifest(manifest: dict, schema: dict) -> list:
    """Structurally validate a manifest against the baseline schema.

    A focused, stdlib-only check (no jsonschema dependency): the top-level required
    set and the sha256/semver patterns are read straight from the schema so this
    stays honest as the schema evolves.
    """
    errors = []
    props = schema.get("properties", {})

    for key in schema.get("required", []):
        if key not in manifest:
            errors.append(f"missing required key: {key}")

    if not isinstance(manifest.get("pluginName"), str) or not manifest.get("pluginName"):
        errors.append("pluginName must be a non-empty string")

    version = manifest.get("pluginVersion", "")
    version_pattern = props.get("pluginVersion", {}).get("pattern")
    if version_pattern and not re.match(version_pattern, version or ""):
        errors.append(f"pluginVersion {version!r} does not match {version_pattern}")

    if not isinstance(manifest.get("templateSetVersion"), str) or not manifest.get(
        "templateSetVersion"
    ):
        errors.append("templateSetVersion must be a non-empty string")

    if not isinstance(manifest.get("stampedAt"), str) or not manifest.get("stampedAt"):
        errors.append("stampedAt must be a non-empty string")

    slots = manifest.get("slots")
    if not isinstance(slots, dict) or any(not isinstance(v, str) for v in slots.values()):
        errors.append("slots must be an object of string values")

    sha_pattern = (
        props.get("files", {})
        .get("items", {})
        .get("properties", {})
        .get("sha256", {})
        .get("pattern", "^[a-f0-9]{64}$")
    )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        errors.append("files must be a non-empty array")
    else:
        for i, entry in enumerate(files):
            if not isinstance(entry, dict):
                errors.append(f"files[{i}] must be an object")
                continue
            for key in ("path", "template", "sha256"):
                if not isinstance(entry.get(key), str) or not entry.get(key):
                    errors.append(f"files[{i}].{key} must be a non-empty string")
            sha = entry.get("sha256")
            if isinstance(sha, str) and not re.match(sha_pattern, sha):
                errors.append(f"files[{i}].sha256 is not a valid sha256")
    return errors


def _iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _verify(root: Path, entries: list, schema: dict) -> list:
    """Return a list of problems with a stamped tree (empty means all good)."""
    problems = []

    for entry in entries:
        if not (root / entry["path"]).is_file():
            problems.append(f"missing stamped file: {entry['path']}")

    for sub in ("rules", "agents", "skills", "hooks"):
        if not (root / ".claude" / sub).is_dir():
            problems.append(f"missing .claude/{sub}/ directory")
    if not (root / ".claude" / "settings.json").is_file():
        problems.append("missing .claude/settings.json")

    for hook in ("pre-commit", "pre-push"):
        path = root / ".githooks" / hook
        if not path.is_file():
            problems.append(f"missing .githooks/{hook}")
        elif not os.access(path, os.X_OK):
            problems.append(f".githooks/{hook} is not executable")

    if not any(e["path"].endswith("CLAUDE.md") for e in entries):
        problems.append("no CLAUDE.md was stamped")

    if not (
        (root / PR_TEMPLATE_PRIMARY).is_file() or (root / PR_TEMPLATE_FALLBACK).is_file()
    ):
        problems.append("no pull request template was stamped")

    baseline = root / BASELINE_RELPATH
    if not baseline.is_file():
        problems.append("missing .claude/.workflow-baseline.json")
    else:
        try:
            manifest = json.loads(baseline.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"baseline manifest is not valid JSON: {exc}")
        else:
            problems.extend(
                f"baseline schema: {err}" for err in _validate_manifest(manifest, schema)
            )

    for path in _iter_text_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "{{" in text:
            problems.append(f"unsubstituted '{{{{' in {path.relative_to(root)}")

    return problems


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
def _read_baseline(target: Path):
    """Return the manifest recorded in an existing baseline, or None if absent.

    A present-but-unreadable baseline yields a sentinel dict so callers can still
    tell the repo was stamped (idempotency guard) without trusting its contents.
    """
    baseline = target / BASELINE_RELPATH
    if not baseline.is_file():
        return None
    try:
        return json.loads(baseline.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"pluginVersion": "unknown", "files": []}


def _remove_orphans(target: Path, prior_manifest, new_paths: set) -> list:
    """Delete files a prior stamp wrote that this stamp no longer writes.

    Keeps a re-stamp from leaving a governance file on disk yet absent from the new
    manifest (e.g. a PR template that shifted paths, or files moved by a mode
    change). Only paths the prior manifest recorded as ours are touched.
    """
    if not prior_manifest:
        return []
    removed = []
    for prior_path in sorted({f.get("path") for f in prior_manifest.get("files", [])}):
        if not prior_path or prior_path in new_paths:
            continue
        stale = target / prior_path
        if stale.is_file():
            stale.unlink()
            removed.append(prior_path)
    return removed


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_stamp(slots, target, mode, subdir, dry_run, force, version=None):
    """Render + place templates into ``target``; return a summary dict.

    On a dry run everything is staged into a throwaway directory and verified, and
    the real target is only *inspected* (for the PR-template collision) — never
    written. Raises :class:`StampError` on a refused idempotency guard.
    """
    version = version or _read_plugin_version()
    schema = _load_schema()
    prior_manifest = _read_baseline(target)
    existing = prior_manifest.get("pluginVersion") if prior_manifest else None
    owns_primary = prior_owns_primary(prior_manifest)

    if existing is not None and not force and not dry_run:
        raise StampError(
            f"{target} is already stamped by {PLUGIN_NAME} v{existing}. "
            f"Re-run with --force to re-stamp."
        )

    stamped_at = now_iso_utc()

    if dry_run:
        with tempfile.TemporaryDirectory(prefix="cmw-dryrun-") as tmp:
            write_root = Path(tmp)
            entries, notes = _place(slots, write_root, target, mode, subdir, owns_primary)
            manifest = _build_manifest(slots, entries, version, stamped_at)
            _write_baseline(write_root, manifest)
            problems = _verify(write_root, entries, schema)
        # Report the stale files a real --force run would clean up, without touching
        # the target on a preview.
        new_paths = {e["path"] for e in entries}
        notes["orphans_removed"] = [
            p
            for p in sorted({f.get("path") for f in (prior_manifest or {}).get("files", [])})
            if p and p not in new_paths and (target / p).is_file()
        ]
    else:
        entries, notes = _place(slots, target, target, mode, subdir, owns_primary)
        manifest = _build_manifest(slots, entries, version, stamped_at)
        _write_baseline(target, manifest)
        new_paths = {e["path"] for e in entries}
        notes["orphans_removed"] = _remove_orphans(target, prior_manifest, new_paths)
        problems = _verify(target, entries, schema)

    return {
        "version": version,
        "mode": mode,
        "subdir": subdir,
        "dry_run": dry_run,
        "existing_version": existing,
        "destinations": [e["path"] for e in entries],
        "baseline_path": BASELINE_RELPATH.as_posix(),
        "notes": notes,
        "problems": problems,
    }


def _print_summary(target: Path, summary: dict) -> None:
    version = summary["version"]
    dry = summary["dry_run"]
    header = "DRY RUN — nothing written to" if dry else f"Stamped {PLUGIN_NAME} v{version} into"
    print(f"{header} {target}")

    mode_line = f"  mode                  : {summary['mode']}"
    if summary["mode"] == "nested":
        mode_line += f" (subdir: {summary['subdir']})"
    print(mode_line)

    if summary["existing_version"] is not None:
        note = "would overwrite" if dry else "re-stamped over"
        print(f"  note                  : {note} an existing v{summary['existing_version']} baseline (--force)")

    print(f"  files ({len(summary['destinations'])}){'  would write' if dry else ''}:")
    for path in summary["destinations"]:
        print(f"    {path}")
    print(f"  baseline manifest     : {summary['baseline_path']}")

    notes = summary["notes"]
    if notes["pr_template_collision"]:
        print(
            "  PR template           : repo already had .github/pull_request_template.md; "
            "wrote .github/pull_request_template.crow-mind.md instead (no clobber)"
        )
    if notes["connectivity_omitted"]:
        print("  connectivity line     : CONNECTIVITY_CMD empty -> dangling comment stripped")
    if notes.get("orphans_removed"):
        verb = "would remove" if dry else "removed"
        print(f"  orphans ({verb})    : " + ", ".join(notes["orphans_removed"]))

    if summary["problems"]:
        print("  verification          : FAILED", file=sys.stderr)
        for problem in summary["problems"]:
            print(f"    - {problem}", file=sys.stderr)
    else:
        print("  verification          : ok")

    if not dry:
        print()
        print("Next — enable the guard hooks in the target repo (blocks commits to main):")
        print("  git config core.hooksPath .githooks")


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
def _assert(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        raise SystemExit(1)


def _has_double_brace(root: Path) -> bool:
    return any("{{" in p.read_text(encoding="utf-8", errors="replace") for p in _iter_text_files(root))


def run_self_test() -> int:
    """Stamp the bundled sample slots into a temp target and assert coherence."""
    version = _read_plugin_version()
    schema = _load_schema()
    slots = render.load_slots(SAMPLE_SLOTS_PATH)

    # Case 1 — a normal root stamp.
    with tempfile.TemporaryDirectory(prefix="cmw-stamp-selftest-") as tmp:
        target = Path(tmp)
        summary = run_stamp(
            slots, target, mode="root", subdir=None, dry_run=False, force=False, version=version
        )
        _assert(not summary["problems"], f"verification problems: {summary['problems']}")

        _assert((target / "CLAUDE.md").is_file(), "CLAUDE.md not at target root")
        for sub in ("rules", "agents", "skills", "hooks"):
            _assert((target / ".claude" / sub).is_dir(), f".claude/{sub}/ missing")
        _assert((target / ".claude" / "settings.json").is_file(), ".claude/settings.json missing")

        for hook in ("pre-commit", "pre-push"):
            path = target / ".githooks" / hook
            _assert(path.is_file(), f".githooks/{hook} missing")
            _assert(os.access(path, os.X_OK), f".githooks/{hook} not executable")

        baseline = target / BASELINE_RELPATH
        _assert(baseline.is_file(), "baseline manifest missing")
        manifest = json.loads(baseline.read_text(encoding="utf-8"))
        errors = _validate_manifest(manifest, schema)
        _assert(not errors, f"baseline manifest invalid: {errors}")
        _assert(
            manifest["pluginName"] == PLUGIN_NAME and manifest["pluginVersion"] == version,
            "baseline manifest name/version mismatch",
        )

        _assert(not _has_double_brace(target), "'{{' left somewhere in stamped tree")
        _assert(
            (target / PR_TEMPLATE_PRIMARY).is_file(),
            "PR template not at .github/pull_request_template.md",
        )

        file_count = len(summary["destinations"])

    # Case 2 — an empty CONNECTIVITY_CMD must leave no dangling comment line.
    with tempfile.TemporaryDirectory(prefix="cmw-stamp-selftest-empty-") as tmp:
        target = Path(tmp)
        empty_slots = dict(slots)
        empty_slots["CONNECTIVITY_CMD"] = ""
        summary_empty = run_stamp(
            empty_slots, target, mode="root", subdir=None, dry_run=False, force=False, version=version
        )
        _assert(not summary_empty["problems"], f"verification problems: {summary_empty['problems']}")
        _assert(
            summary_empty["notes"]["connectivity_omitted"],
            "connectivity omission was not recorded",
        )

        claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
        _assert(
            "verify external connectivity" not in claude_md,
            "dangling connectivity comment remains in CLAUDE.md",
        )
        readme = (target / "README-governance.md").read_text(encoding="utf-8")
        _assert(
            "verify the setup / external connectivity" not in readme,
            "dangling connectivity comment remains in README-governance.md",
        )
        _assert(not _has_double_brace(target), "'{{' left in empty-connectivity stamp")

    # Case 3 — a --force re-stamp is placement-stable for our own PR template.
    with tempfile.TemporaryDirectory(prefix="cmw-stamp-selftest-force-") as tmp:
        target = Path(tmp)
        run_stamp(slots, target, mode="root", subdir=None, dry_run=False, force=False, version=version)
        _assert(
            (target / PR_TEMPLATE_PRIMARY).is_file(),
            "first stamp did not write the primary PR template",
        )

        forced = run_stamp(
            slots, target, mode="root", subdir=None, dry_run=False, force=True, version=version
        )
        _assert(not forced["problems"], f"verification problems on --force: {forced['problems']}")
        _assert(
            (target / PR_TEMPLATE_PRIMARY).is_file(),
            "primary PR template lost on --force re-stamp",
        )
        _assert(
            not (target / PR_TEMPLATE_FALLBACK).exists(),
            "--force re-stamp orphaned a .crow-mind.md template",
        )

        manifest = json.loads((target / BASELINE_RELPATH).read_text(encoding="utf-8"))
        primary_entries = [
            f for f in manifest["files"] if f["path"] == PR_TEMPLATE_PRIMARY.as_posix()
        ]
        _assert(
            len(primary_entries) == 1
            and primary_entries[0]["template"] == PR_TEMPLATE_SOURCE.as_posix(),
            "manifest does not record the primary PR template as ours after --force",
        )
        _assert(
            not any(f["path"] == PR_TEMPLATE_FALLBACK.as_posix() for f in manifest["files"]),
            "manifest still references a .crow-mind.md template after --force",
        )

    print("PASS: crow-mind-workflow init-repo stamp is coherent")
    print(f"  plugin version            : {version}")
    print(f"  files stamped (case 1)    : {file_count}")
    print(f"  .claude rules/agents/skills/hooks + settings.json : present")
    print(f"  .githooks pre-commit/pre-push : present + executable")
    print(f"  baseline manifest valid   : ok (schema-checked)")
    print(f"  PR template               : .github/pull_request_template.md")
    print(f"  no unsubstituted '{{{{'      : ok")
    print(f"  empty CONNECTIVITY_CMD    : dangling comment stripped (CLAUDE.md + README)")
    print(f"  --force re-stamp          : PR template stable at primary path, no orphan")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stamp a target repo with the crow-mind-workflow governance baseline.",
    )
    parser.add_argument("--slots", type=Path, help="JSON file of slot values")
    parser.add_argument("--target", type=Path, help="target repo directory")
    parser.add_argument(
        "--mode",
        choices=("root", "nested"),
        default="root",
        help="root: stamp the whole repo; nested: place CLAUDE.md under --subdir",
    )
    parser.add_argument("--subdir", help="sub-app directory (required for --mode nested)")
    parser.add_argument("--dry-run", action="store_true", help="preview only; write nothing to the target")
    parser.add_argument("--force", action="store_true", help="re-stamp even if a baseline already exists")
    parser.add_argument("--self-test", action="store_true", help="stamp sample slots into a temp target and verify")
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not (args.slots and args.target):
        parser.error("--slots and --target are required (or use --self-test)")

    if args.mode == "nested" and not args.subdir:
        parser.error("--mode nested requires --subdir")
    if args.mode == "root" and args.subdir:
        parser.error("--subdir is only valid with --mode nested")

    try:
        slots = render.load_slots(args.slots)
        summary = run_stamp(
            slots,
            args.target,
            mode=args.mode,
            subdir=args.subdir,
            dry_run=args.dry_run,
            force=args.force,
        )
    except StampError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _print_summary(args.target, summary)
    return 1 if summary["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
