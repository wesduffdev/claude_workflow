#!/usr/bin/env python3
"""Publish the crow-mind-workflow **Workflow** wiki page to a repo's GitHub Wiki.

The init-repo skill stamps governance *into* a target repo; this script takes the
one human-facing page that belongs *outside* the working tree — the living
**Workflow** page — and publishes it to the repo's separate GitHub Wiki git
repository. Home and _Sidebar are seeded too, but only when the wiki does not
already have them (never clobbering a wiki a team has started curating).

``render.py`` is the substitution primitive; this script never reimplements it. The
parameterized pages live in ``../wiki-templates`` (kept out of ``templates/`` on
purpose, so ``stamp.py`` never lays them into the target working tree — they go only
to the wiki repo).

Design seams (why this reads the way it does)
---------------------------------------------
Two decisions are isolated behind injectable callables so the whole flow is testable
with no network, clone, or push:

* ``probe`` — is the wiki initialized? (default: ``git ls-remote``)
* ``clone_fn`` — get a working copy of the wiki (default: ``git clone``)

Publishing is a PUBLISH, so it is **gated**: by default nothing is pushed — the
script previews what *would* change. It pushes only when ``--push`` is given (the
skill supplies it *after* a human confirms), and ``--dry-run`` forces no-push even
then.

CLI
---
::

    publish_wiki.py --slots <values.json> [--push] [--dry-run] [--self-test]

Behavior:
  * Availability: if the wiki is not initialized, print enable-wiki guidance and
    **exit 0** (a graceful skip — an un-initialized wiki is not an error).
  * Available: clone the wiki, render the pages (Workflow always; Home/_Sidebar only
    if absent), and either preview (default) or, with ``--push``, commit and push.

Self-test (no network / clone / push)::

    publish_wiki.py --self-test
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Reuse the shared render engine (never reimplement substitution or the forbidden-
# literal scan). render.py resolves its own paths from __file__, so importing it is
# CWD-independent.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import render  # noqa: E402

PLUGIN_DIR = SCRIPT_DIR.parent
WIKI_TEMPLATES_DIR = PLUGIN_DIR / "wiki-templates"
SAMPLE_SLOTS_PATH = SCRIPT_DIR / "sample-slots.json"

# The one page that is always (re)published; the others are seeded only when the
# wiki lacks them, so a curated wiki's landing page and nav are never clobbered.
WORKFLOW_PAGE = "Workflow.md"

COMMIT_MESSAGE = "docs: update Workflow page (crow-mind-workflow)"

# The wiki commit uses an explicit, self-describing identity so publishing never
# depends on (or is attributed to) whatever ambient git config the box happens to
# carry — and never fails with git's "please tell me who you are".
COMMIT_AUTHOR_NAME = "crow-mind-workflow"
COMMIT_AUTHOR_EMAIL = "crow-mind-workflow@users.noreply.github.com"

# git ls-remote / clone must not hang on an unreachable host.
GIT_TIMEOUT_SECONDS = 20

# A wiki URL must use a known transport and must not look like a git option; this
# guards `git ls-remote`/`clone` against an argument-injection URL beginning with '-'.
_URL_SCHEME_RE = re.compile(r"^(https?|git|ssh)://")
_SCP_LIKE_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:")


class PublishError(Exception):
    """Raised on an actual failure (bad slots, clone or push failure)."""


# --------------------------------------------------------------------------- #
# Wiki location
# --------------------------------------------------------------------------- #
def wiki_git_url_from_slots(slots: dict) -> str:
    """Resolve (and validate) the wiki's git clone URL from *slots*.

    Prefers an explicit ``WIKI_GIT_URL``; otherwise derives the GitHub convention
    ``https://github.com/<owner>/<repo>.wiki.git`` from ``GH_OWNER``/``GH_REPO``.
    """
    explicit = str(slots.get("WIKI_GIT_URL", "")).strip()
    if explicit:
        return _validate_wiki_url(explicit)

    owner = str(slots.get("GH_OWNER", "")).strip()
    repo = str(slots.get("GH_REPO", "")).strip()
    if not owner or not repo:
        raise PublishError(
            "cannot determine the wiki URL: supply WIKI_GIT_URL, or GH_OWNER and "
            "GH_REPO to derive https://github.com/<owner>/<repo>.wiki.git"
        )
    return _validate_wiki_url(f"https://github.com/{owner}/{repo}.wiki.git")


def _validate_wiki_url(url: str) -> str:
    """Return *url* unchanged if it is a safe git remote; raise otherwise.

    Rejects a URL that begins with ``-`` (which git would read as an option) and
    requires a recognized transport (http(s)/git/ssh, or scp-like ``user@host:path``).
    """
    if url.startswith("-"):
        raise PublishError(f"refusing wiki URL that begins with '-': {url!r}")
    if not (_URL_SCHEME_RE.match(url) or _SCP_LIKE_RE.match(url)):
        raise PublishError(
            f"wiki URL must use an http(s), git, or ssh transport: {url!r}"
        )
    return url


# --------------------------------------------------------------------------- #
# Injectable git seams (real implementations; stubbed in --self-test)
# --------------------------------------------------------------------------- #
def _git_env() -> dict:
    """Environment for git calls: never block on an interactive credential prompt.

    A missing or private wiki must make the availability probe *fail fast* (so we
    skip gracefully), not hang waiting for a username/password at a dead terminal.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def probe_wiki(wiki_git_url: str) -> bool:
    """Return True iff the wiki repo is initialized and reachable.

    ``git ls-remote`` on an un-initialized wiki fails (or lists nothing); either case
    means "not available", which callers treat as a graceful skip, not an error.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--", wiki_git_url],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            env=_git_env(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _git_clone(wiki_git_url: str, dest: Path) -> None:
    """Clone the wiki repo into *dest* (which must not yet exist)."""
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--", wiki_git_url, str(dest)],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
            env=_git_env(),
        )
    except subprocess.CalledProcessError as exc:
        raise PublishError(f"failed to clone the wiki: {exc.stderr.strip()}") from exc
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise PublishError(f"failed to clone the wiki: {exc}") from exc


def _git(clone_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command inside *clone_dir*, raising PublishError on failure."""
    try:
        return subprocess.run(
            ["git", "-C", str(clone_dir), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=True,
            env=_git_env(),
        )
    except subprocess.CalledProcessError as exc:
        raise PublishError(f"git {' '.join(args)} failed: {exc.stderr.strip()}") from exc
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise PublishError(f"git {' '.join(args)} failed: {exc}") from exc


# --------------------------------------------------------------------------- #
# Rendering + page selection
# --------------------------------------------------------------------------- #
def _existing_pages(clone_dir: Path) -> set:
    """Return the set of page file names already present in a cloned wiki."""
    names = set()
    for child in clone_dir.iterdir():
        if child.name == ".git":
            continue
        if child.is_file():
            names.add(child.name)
    return names


def _select_pages(rendered: list, existing: set) -> tuple:
    """Split rendered pages into (to_write, skipped) by the seed-if-absent rule.

    The Workflow page is always (re)published; every other page (Home, _Sidebar) is
    written only when the wiki does not already carry it.
    """
    to_write, skipped = [], []
    for page in rendered:
        if page == WORKFLOW_PAGE or page not in existing:
            to_write.append(page)
        else:
            skipped.append(page)
    return sorted(to_write), sorted(skipped)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _print_unavailable_guidance(wiki_git_url: str) -> None:
    print(f"Wiki not available at {wiki_git_url}")
    print("The wiki repository is not initialized yet, so there is nothing to")
    print("publish to. This is expected for a brand-new repo and is not an error.")
    print()
    print("To enable it:")
    print("  1. In the GitHub repo settings, turn on the 'Wiki' feature.")
    print("  2. Create the first page once in the GitHub UI (e.g. the Home page).")
    print("  3. Re-run init-repo (or publish_wiki.py) to publish the Workflow page.")
    print()
    print("Skipping wiki publish (any repo stamping already succeeded).")


def _print_plan(wiki_git_url, to_write, skipped, existing, stage_dir, will_push) -> None:
    print(f"Wiki available at {wiki_git_url}")
    print("Pages to publish:")
    for page in to_write:
        tag = "update" if page in existing else "new"
        print(f"  + {page} ({tag})")
    for page in skipped:
        print(f"  = {page} (already in the wiki — left as-is)")

    # On the confirmation path (a preview, before any push) the human must be able to
    # read the ENTIRE page they are approving — never a truncated slice — so print the
    # full rendered Workflow page. On the push path it was already confirmed, so the
    # page list above is enough.
    if not will_push:
        workflow_stage = stage_dir / WORKFLOW_PAGE
        if workflow_stage.is_file():
            print()
            print(f"Full rendered {WORKFLOW_PAGE} to be published:")
            print("-" * 60)
            print(workflow_stage.read_text(encoding="utf-8").rstrip("\n"))
            print("-" * 60)
        print()
        print("Preview only — nothing was pushed. This is a PUBLISH: after a human")
        print("reviews the full Workflow page above and confirms, re-run with --push")
        print("to publish.")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_publish(slots, push, dry_run, probe=probe_wiki, clone_fn=_git_clone) -> dict:
    """Publish (or preview) the wiki pages; return a structured result.

    Availability, cloning, rendering, and page selection are all done against a
    throwaway clone in a temp dir, so a failure never leaves a partial state and the
    user's tree is never touched. Returns a dict describing what happened; raises
    :class:`PublishError` only on an actual failure (bad slots, clone/push error).
    """
    wiki_git_url = wiki_git_url_from_slots(slots)

    if not probe(wiki_git_url):
        _print_unavailable_guidance(wiki_git_url)
        return {"available": False, "wiki_git_url": wiki_git_url, "pushed": False}

    will_push = bool(push) and not dry_run

    with tempfile.TemporaryDirectory(prefix="cmw-wiki-clone-") as clone_tmp, \
            tempfile.TemporaryDirectory(prefix="cmw-wiki-stage-") as stage_tmp:
        clone_dir = Path(clone_tmp) / "wiki"  # git clone creates this leaf
        stage_dir = Path(stage_tmp)

        clone_fn(wiki_git_url, clone_dir)
        existing = _existing_pages(clone_dir)

        # render_tree renders ALL pages and enforces "no leftover placeholder" for us.
        try:
            rendered = render.render_tree(slots, WIKI_TEMPLATES_DIR, stage_dir)
        except render.RenderError as exc:
            raise PublishError(str(exc)) from exc

        to_write, skipped = _select_pages(rendered, existing)
        for page in to_write:
            shutil.copy2(stage_dir / page, clone_dir / page)

        _print_plan(wiki_git_url, to_write, skipped, existing, stage_dir, will_push)

        pushed = False
        if will_push:
            pushed = _commit_and_push(clone_dir, to_write)

    return {
        "available": True,
        "wiki_git_url": wiki_git_url,
        "written": to_write,
        "skipped": skipped,
        "existing": sorted(existing),
        "pushed": pushed,
    }


def _has_staged_changes(clone_dir: Path) -> bool:
    """True iff there is staged content to commit.

    Scoped to the index (``git diff --cached --quiet``) so a stray untracked file in
    the clone cannot push us into an empty-commit error. ``--quiet`` exits 0 with no
    staged diff and non-zero when there is one — a signal, not a failure — so this
    does not use the raising :func:`_git` helper.
    """
    result = subprocess.run(
        ["git", "-C", str(clone_dir), "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
        env=_git_env(),
    )
    return result.returncode != 0


def _commit_and_push(clone_dir: Path, to_write: list) -> bool:
    """Commit the written pages and push. Returns True iff a push happened.

    A no-op (the wiki already matches the rendered pages) is reported and skipped
    rather than erroring on an empty commit.
    """
    for page in to_write:
        _git(clone_dir, "add", "--", page)

    if not _has_staged_changes(clone_dir):
        print()
        print("Wiki already up to date — nothing to push.")
        return False

    # Explicit identity: publishing never depends on ambient git config (and never
    # fails with git's "please tell me who you are" on a box without one).
    _git(
        clone_dir,
        "-c", f"user.name={COMMIT_AUTHOR_NAME}",
        "-c", f"user.email={COMMIT_AUTHOR_EMAIL}",
        "commit", "-m", COMMIT_MESSAGE,
    )
    _git(clone_dir, "push")
    print()
    print("Published: Workflow page pushed to the wiki.")
    return True


# --------------------------------------------------------------------------- #
# Self-test (no network / clone / push)
# --------------------------------------------------------------------------- #
def _assert(condition: bool, message: str) -> None:
    if not condition:
        print(f"FAIL: {message}", file=sys.stderr)
        raise SystemExit(1)


def _stub_clone_empty(wiki_git_url: str, dest: Path) -> None:
    """Stand-in for a clone of an initialized-but-empty wiki."""
    dest.mkdir(parents=True, exist_ok=True)


def _stub_clone_with_home(wiki_git_url: str, dest: Path) -> None:
    """Stand-in for a clone of a wiki that already curates its own Home page."""
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "Home.md").write_text("# curated home — do not clobber\n", encoding="utf-8")


def _stub_clone_forbidden(wiki_git_url: str, dest: Path) -> None:  # pragma: no cover
    raise AssertionError("clone must not run when the wiki is unavailable")


def run_self_test() -> int:
    """Prove the pages render cleanly and both availability branches behave.

    Uses the bundled sample slots and stubbed git seams — no network, clone, or push.
    """
    if not WIKI_TEMPLATES_DIR.is_dir():
        print(f"FAIL: wiki-templates dir not found at {WIKI_TEMPLATES_DIR}", file=sys.stderr)
        return 1

    slots = render.load_slots(SAMPLE_SLOTS_PATH)

    # (1) The pages render cleanly with sample values.
    with tempfile.TemporaryDirectory(prefix="cmw-wiki-selftest-") as tmp:
        stage = Path(tmp)
        try:
            rendered = render.render_tree(slots, WIKI_TEMPLATES_DIR, stage)
        except render.RenderError as exc:
            print("FAIL (1): placeholders left unsubstituted", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 1

        for page in (WORKFLOW_PAGE, "Home.md", "_Sidebar.md"):
            _assert((stage / page).is_file(), f"{page} not rendered")

        # Defense-in-depth: reuse render's public scanners so the forbidden-literal
        # list stays single-sourced.
        placeholders = render.find_placeholder_files(stage)
        _assert(not placeholders, f"'{{{{' left in rendered wiki pages: {placeholders}")

        forbidden = render.find_forbidden_hits(stage)
        _assert(not forbidden, f"forbidden source literal(s) in wiki pages: {forbidden}")

        rendered_count = len(rendered)

    # The three flow checks exercise run_publish's own console output; capture it so
    # the self-test's PASS summary reads cleanly. Behavior is asserted via the result.
    sink = io.StringIO()

    # (2) Availability DECISION — unavailable: guidance + graceful exit 0, no clone.
    with contextlib.redirect_stdout(sink):
        unavailable = run_publish(
            slots, push=True, dry_run=False,
            probe=lambda url: False, clone_fn=_stub_clone_forbidden,
        )
    _assert(unavailable["available"] is False, "unavailable branch did not report unavailable")
    _assert(unavailable["pushed"] is False, "unavailable branch must not push")
    _assert("not initialized" in sink.getvalue(), "unavailable branch did not print guidance")

    # (3) Availability DECISION — available, empty wiki, dry mode: render + preview,
    #     seed all pages, never push.
    with contextlib.redirect_stdout(sink):
        empty_wiki = run_publish(
            slots, push=True, dry_run=True,
            probe=lambda url: True, clone_fn=_stub_clone_empty,
        )
    _assert(empty_wiki["available"] is True, "available branch did not report available")
    _assert(empty_wiki["pushed"] is False, "--dry-run must force no-push")
    for page in (WORKFLOW_PAGE, "Home.md", "_Sidebar.md"):
        _assert(page in empty_wiki["written"], f"{page} not seeded into an empty wiki")

    # (4) Seed-if-absent DECISION — a wiki that already has Home keeps its own Home,
    #     yet the Workflow page is still (re)published.
    with contextlib.redirect_stdout(sink):
        seeded_wiki = run_publish(
            slots, push=False, dry_run=False,
            probe=lambda url: True, clone_fn=_stub_clone_with_home,
        )
    _assert(WORKFLOW_PAGE in seeded_wiki["written"], "Workflow page must always publish")
    _assert("_Sidebar.md" in seeded_wiki["written"], "_Sidebar should seed when absent")
    _assert("Home.md" in seeded_wiki["skipped"], "existing Home.md must not be clobbered")
    _assert(seeded_wiki["pushed"] is False, "default (no --push) must not push")

    print("PASS: crow-mind-workflow wiki publish is coherent")
    print(f"  wiki pages rendered       : {rendered_count} (Workflow, Home, _Sidebar)")
    print(f"  no unsubstituted '{{{{'      : ok")
    print(f"  forbidden literals absent : {len(render.FORBIDDEN_LITERALS)} checked, 0 found")
    print(f"  unavailable wiki          : guidance + exit 0, no clone")
    print(f"  available empty wiki      : all pages seeded, dry-run forced no-push")
    print(f"  seed-if-absent            : existing Home kept, Workflow re-published")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish the crow-mind-workflow Workflow page to a repo's GitHub Wiki.",
    )
    parser.add_argument("--slots", type=Path, help="JSON file of slot values")
    parser.add_argument(
        "--push",
        action="store_true",
        help="publish (commit + push); default is preview only. This is a PUBLISH — "
        "the skill passes --push only after a human confirms.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="force preview only; never push even if --push is given",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="render the wiki pages + exercise both availability branches (no network)",
    )
    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.slots:
        parser.error("--slots is required (or use --self-test)")

    try:
        slots = render.load_slots(args.slots)
        run_publish(slots, push=args.push, dry_run=args.dry_run)
    except PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
