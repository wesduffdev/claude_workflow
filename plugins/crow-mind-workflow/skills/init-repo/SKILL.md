---
name: init-repo
description: Stamp a target repository with the crow-mind engineering-governance workflow (CLAUDE.md, the .claude/ Tool-Gateway layout, guard git hooks, a README governance index, and a PR template) and write a baseline manifest recording exactly what was stamped. Use when bootstrapping a new repo, onboarding an existing repo to the crow-mind baseline, or when the user asks to "init repo", "stamp the workflow", "apply the governance rules", or "set up CLAUDE.md".
user-invocable: true
---

# init-repo

Stamp a **target repository** with the crow-mind governance workflow and record a
**baseline manifest** so [`sync-baseline`](../sync-baseline/SKILL.md) can detect
drift later. This skill stamps **governance files only** — it never touches
application code.

The substitution + placement engine lives in
`${CLAUDE_PLUGIN_ROOT}/scripts/stamp.py` (built on `scripts/render.py`). This skill
is the human-facing procedure that drives it; the script owns the rules for *where*
each file lands and *what* gets recorded.

Follow the steps in order.

## (0) Version-check preflight

Read `${CLAUDE_PLUGIN_DATA}/version-status.json` (written by the version-check
SessionStart hook; shape `{status, installed, latest, checkedAt, updateInstructions}`).

- If it is missing or unreadable, continue silently.
- If `status == "behind"`, **surface `updateInstructions` to the user before doing
  anything else** so they can update the plugin first. Do not block — let them
  decide whether to proceed on the older version.

## (1) Root or nested?

Ask the user how to stamp:

- **root** — a whole-repo stamp. `CLAUDE.md` goes to the repo root.
- **nested** — a monorepo sub-app stamp. `CLAUDE.md` goes under a **subdir** the
  user names (e.g. `apps/web`). Ask for that subdir.

Either way the shared governance infrastructure — `.claude/**`, `.githooks/**`, the
README governance index, and the PR template — is placed at the **repo root**
(that is where Claude Code and git look for it). Only `CLAUDE.md` moves into the
subdir in nested mode.

Also confirm the **target repo path** (absolute).

## (2) Interview for the 13 slots

Read the slot definitions from `${CLAUDE_PLUGIN_ROOT}/templates/slots.yml`. For each
slot, ask its `prompt`, offering the `default` where present. Notes:

- `WIKI_URL` and `WIKI_GIT_URL` are **derived** from `GH_OWNER` / `GH_REPO`:
  - `WIKI_URL` = `https://github.com/<GH_OWNER>/<GH_REPO>/wiki`
  - `WIKI_GIT_URL` = `https://github.com/<GH_OWNER>/<GH_REPO>.wiki.git`

  Offer the derived value; only ask for an override for a non-GitHub wiki. Fill
  these in yourself — do not leave the raw `{{GH_OWNER}}` placeholders in.
- `CONNECTIVITY_CMD` is **optional** — empty is allowed. When it is empty the
  stamper drops the now-dangling "verify connectivity" comment line automatically,
  so leaving it blank produces clean output.
- Every `required` slot must have a non-empty answer before proceeding.

**Show the collected values back to the user and get confirmation** before stamping.

## (3) Dry-run preview, then stamp

Write the confirmed values to a temp JSON file, then preview:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stamp.py" \
  --slots <temp-values.json> --target <target-repo> \
  [--mode root | --mode nested --subdir <subdir>] --dry-run
```

Show the user the file list the dry-run prints (nothing is written to the target on
a dry-run). If it looks right, run the real stamp by dropping `--dry-run`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/stamp.py" \
  --slots <temp-values.json> --target <target-repo> \
  [--mode root | --mode nested --subdir <subdir>]
```

Idempotency: if the target already carries `.claude/.workflow-baseline.json` the
stamp **refuses** (printing the recorded version). Re-stamp only with `--force`, and
confirm with the user first.

## (4) Report + enablement

Tell the user:

- **What was written** — the file list from the stamp output — and the **baseline
  manifest** at `<target>/.claude/.workflow-baseline.json`.
- The one-time **guard-hook enablement** they must run in the target repo (the hooks
  block direct commits/pushes to `main`):

  ```bash
  git config core.hooksPath .githooks
  ```

- This stamped **governance files only** — never application code.
- **README:** the governance index was written as `README-governance.md` so an
  existing `README.md` is never clobbered. If the repo already had a `README.md`,
  the user should fold the governance index into it (or link to it) and delete
  `README-governance.md`.
- **PR template:** if the repo already had `.github/pull_request_template.md`, the
  crow-mind template was written to `.github/pull_request_template.crow-mind.md`
  instead. The user should merge the checklist they want into their own template.

## (5) Publish the Workflow page to the Wiki (approval-gated)

After a **successful** stamp, offer to publish the living **Workflow** page (and, if
the wiki is brand-new, a `Home` and `_Sidebar`) to the target repo's GitHub Wiki. The
wiki is a separate git repository derived from `WIKI_GIT_URL`; the pages come from
`${CLAUDE_PLUGIN_ROOT}/wiki-templates/` and are rendered with the **same** slot values
you just stamped with (reuse the temp values JSON from step 3).

Pushing to the wiki is a **PUBLISH** — a protected write — so it is **never
automatic**. It happens only after the user explicitly confirms.

**(5a) Check availability + preview (no push).**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/publish_wiki.py" \
  --slots <temp-values.json> --dry-run
```

- If the script reports the **wiki is not available**, it prints enable-wiki guidance
  and exits cleanly. Relay that guidance to the user (enable **Wiki** in the repo's
  GitHub settings, create the first page once in the UI, then re-run) and **continue**
  — the stamp already succeeded; wiki publishing is a bonus, not a failure.
- If the **wiki is available**, the script prints the pages it would write and the
  **full rendered Workflow page** (not a truncated preview). **Present that entire
  rendered Workflow page to the user and ask for explicit confirmation** before
  publishing — the human approves the complete content, not a snippet of it.

**(5b) Publish only on confirmation.**

Once the user confirms, publish with `--push` (dropping `--dry-run`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/publish_wiki.py" \
  --slots <temp-values.json> --push
```

- The Workflow page is always (re)published; `Home`/`_Sidebar` are seeded **only if
  the wiki does not already have them** (an existing curated Home is never clobbered).
- If the user declines, do not push — the Workflow page can be published later by
  re-running this step.
