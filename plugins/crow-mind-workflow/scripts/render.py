#!/usr/bin/env python3
"""Dependency-free render engine for the crow-mind-workflow baseline templates.

This engine copies a template tree to an output directory, substituting every
``{{KEY}}`` placeholder with the matching slot value. It is the shared stamping
primitive reused by the init-repo skill, so the CLI contract below is stable and
intentionally small (Python 3 stdlib only — no third-party imports).

CLI
---
Render a template tree with a set of slot values::

    render.py --slots <values.json> --templates <dir> --out <dir>

    * Copies the template tree from ``--templates`` to ``--out``.
    * Substitutes every ``{{KEY}}`` with ``values[KEY]`` (values.json is a flat
      JSON object of string values).
    * Preserves file modes, so executable templates (``*.sh``, git hooks) stay
      executable.
    * The slot-definition manifest ``slots.yml`` at the template root is METADATA
      and is skipped — it is never stamped into a target repo.
    * FAILS (non-zero exit, message listing files and the offending tokens) if any
      ``{{...}}`` placeholder is left unsubstituted after rendering.

Self-test (proves the bundled templates render cleanly)::

    render.py --self-test

    Renders ``../templates`` with the bundled ``sample-slots.json`` into a temp
    directory and asserts:
      (a) no ``{{`` remains anywhere in the rendered output;
      (b) every rendered ``*.json`` parses as valid JSON;
      (c) none of the source-specific forbidden literals leak into the output.
    Exits non-zero on the first failed assertion; prints a PASS summary otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

# A placeholder is ``{{KEY}}`` where KEY is an identifier. Unknown keys are left
# intact so they surface as leftovers (a rendering failure) rather than silently
# vanishing.
TOKEN_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")

# The slot-definition manifest lives inside templates/ for discoverability but is
# plugin metadata, not a file to stamp into a target repo. Skip it when rendering.
MANIFEST_FILENAMES = {"slots.yml"}

# Locations resolved relative to this script, used by --self-test.
SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SCRIPT_DIR.parent
DEFAULT_TEMPLATES_DIR = PLUGIN_DIR / "templates"
SAMPLE_SLOTS_PATH = SCRIPT_DIR / "sample-slots.json"

# Source-specific literals that must never leak into a rendered target repo.
# Checked case-insensitively by the self-test. Keep in sync with the slot map.
FORBIDDEN_LITERALS = (
    "oodo",
    "odoo",
    "linear-personal",
    "init team",
    "uv run",
    "pytest",
    "wesduffdev/oodo_agent",
)


class RenderError(Exception):
    """Raised when rendering leaves one or more placeholders unsubstituted."""


def substitute(text: str, slots: dict) -> str:
    """Replace every known ``{{KEY}}`` in *text*; leave unknown tokens intact.

    Public entry point of the shared render engine — stamp.py (init-repo) and
    sync-baseline reuse this so substitution lives in exactly one place.
    """

    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key in slots:
            return str(slots[key])
        return match.group(0)  # unknown -> kept so it is reported as a leftover

    return TOKEN_RE.sub(replace, text)


def _leftover_tokens(text: str) -> list:
    """Return the sorted, unique placeholder tokens still present in *text*."""
    return sorted(set(m.group(0) for m in TOKEN_RE.finditer(text)))


def _iter_template_files(templates_dir: Path):
    """Yield (source_path, relative_path) for every file to render.

    Walks the whole tree (including dot-directories such as ``.claude`` and
    ``.githooks``) and skips the slot-definition manifest at the tree root.
    """
    for root, _dirs, files in os.walk(templates_dir):
        for name in files:
            src = Path(root) / name
            rel = src.relative_to(templates_dir)
            if rel.parent == Path(".") and name in MANIFEST_FILENAMES:
                continue
            yield src, rel


def render_tree(slots: dict, templates_dir: Path, out_dir: Path) -> list:
    """Render *templates_dir* into *out_dir* using *slots*.

    Returns the list of rendered relative paths. Raises :class:`RenderError` if any
    file still contains a ``{{...}}`` placeholder after substitution.
    """
    rendered = []
    leftovers = {}  # relative path (str) -> list of leftover tokens

    for src, rel in _iter_template_files(templates_dir):
        original = src.read_text(encoding="utf-8")
        result = substitute(original, slots)

        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(result, encoding="utf-8")
        shutil.copymode(src, dst)  # keep executable bits (*.sh, git hooks)

        rendered.append(str(rel))

        if "{{" in result:
            leftovers[str(rel)] = _leftover_tokens(result) or ["{{ (unmatched)"]

    if leftovers:
        lines = ["Unsubstituted placeholders remain after rendering:"]
        for path in sorted(leftovers):
            lines.append(f"  {path}: {', '.join(leftovers[path])}")
        lines.append(
            "Add the missing keys to the slots file, then re-render."
        )
        raise RenderError("\n".join(lines))

    return rendered


def load_slots(path: Path) -> dict:
    """Load a flat JSON object of slot values from *path*.

    Public entry point of the shared render engine (see :func:`substitute`).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"error: {path} must contain a JSON object of slot values")
    return data


# Backward-compatible aliases: the underscore names predate the public API. Kept
# so any earlier caller keeps working; new code should use the public names.
_substitute = substitute
_load_slots = load_slots


def run_render(slots_path: Path, templates_dir: Path, out_dir: Path) -> int:
    """Handle the ``--slots/--templates/--out`` invocation. Returns an exit code."""
    slots = load_slots(slots_path)
    try:
        rendered = render_tree(slots, templates_dir, out_dir)
    except RenderError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Rendered {len(rendered)} file(s) to {out_dir}")
    return 0


def _find_json_failures(out_dir: Path) -> list:
    """Return (path, error) for every rendered ``*.json`` that fails to parse."""
    failures = []
    for path in sorted(out_dir.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append((path.relative_to(out_dir), str(exc)))
    return failures


def _find_forbidden_hits(out_dir: Path) -> list:
    """Return (path, literal) for every forbidden literal found in the output."""
    hits = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        haystack = path.read_text(encoding="utf-8", errors="replace").lower()
        for literal in FORBIDDEN_LITERALS:
            if literal in haystack:
                hits.append((path.relative_to(out_dir), literal))
    return hits


def _find_placeholder_files(out_dir: Path) -> list:
    """Return (path, tokens) for every rendered file that still has ``{{``."""
    offenders = []
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "{{" in text:
            offenders.append((path.relative_to(out_dir), _leftover_tokens(text)))
    return offenders


def run_self_test() -> int:
    """Render the bundled templates with sample values and assert cleanliness."""
    if not DEFAULT_TEMPLATES_DIR.is_dir():
        print(f"FAIL: templates dir not found at {DEFAULT_TEMPLATES_DIR}", file=sys.stderr)
        return 1
    if not SAMPLE_SLOTS_PATH.is_file():
        print(f"FAIL: sample slots not found at {SAMPLE_SLOTS_PATH}", file=sys.stderr)
        return 1

    slots = load_slots(SAMPLE_SLOTS_PATH)

    with tempfile.TemporaryDirectory(prefix="cmw-selftest-") as tmp:
        out_dir = Path(tmp)

        # Rendering itself enforces "no leftover placeholders" by raising.
        try:
            rendered = render_tree(slots, DEFAULT_TEMPLATES_DIR, out_dir)
        except RenderError as exc:
            print("FAIL (a): placeholders left unsubstituted", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 1

        # (a) Defense-in-depth: no `{{` anywhere in the rendered output.
        placeholder_files = _find_placeholder_files(out_dir)
        if placeholder_files:
            print("FAIL (a): `{{` found in rendered output:", file=sys.stderr)
            for path, tokens in placeholder_files:
                print(f"  {path}: {', '.join(tokens)}", file=sys.stderr)
            return 1

        # (b) Every rendered *.json parses.
        json_failures = _find_json_failures(out_dir)
        if json_failures:
            print("FAIL (b): rendered JSON did not parse:", file=sys.stderr)
            for path, err in json_failures:
                print(f"  {path}: {err}", file=sys.stderr)
            return 1

        # (c) No source-specific literal leaked through.
        forbidden = _find_forbidden_hits(out_dir)
        if forbidden:
            print("FAIL (c): forbidden source literal(s) in rendered output:", file=sys.stderr)
            for path, literal in forbidden:
                print(f"  {path}: contains {literal!r}", file=sys.stderr)
            return 1

        json_count = len(list(out_dir.rglob("*.json")))

    print("PASS: crow-mind-workflow templates render cleanly")
    print(f"  files rendered            : {len(rendered)}")
    print(f"  no unsubstituted `{{{{`     : ok")
    print(f"  rendered JSON files valid : {json_count}")
    print(f"  forbidden literals absent : {len(FORBIDDEN_LITERALS)} checked, 0 found")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render the crow-mind-workflow baseline templates.",
    )
    parser.add_argument("--slots", type=Path, help="JSON file of slot values")
    parser.add_argument("--templates", type=Path, help="template tree to render")
    parser.add_argument("--out", type=Path, help="output directory")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="render bundled templates with sample values and verify cleanliness",
    )
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not (args.slots and args.templates and args.out):
        parser.error("--slots, --templates and --out are required (or use --self-test)")

    return run_render(args.slots, args.templates, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
