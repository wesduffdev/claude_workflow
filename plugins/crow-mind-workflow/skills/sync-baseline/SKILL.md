---
name: sync-baseline
description: Check a repo's stamped crow-mind baseline against the plugin's CURRENT templates and report drift — files the plugin updated (behind), files you hand-edited (local modifications / conflicts), missing files, brand-new templates, unfilled/renamed slots, and whether the stamp trails the installed plugin version. Then, only with explicit approval, update the safe files and refresh the manifest. Use when the user asks to "sync the baseline", "check governance drift", "am I on the latest base rules?", or after the plugin version bumps.
user-invocable: true
---

# sync-baseline

Reconcile a **stamped repository** with the crow-mind governance workflow: report
how the repo has drifted from the plugin's current templates, and — **only after
explicit approval** — update the safe files and refresh the baseline manifest. This
skill writes governance files, so the update step is **approval-gated** and it
**never overwrites your hand-edits silently**.

The comparison engine lives in `${CLAUDE_PLUGIN_ROOT}/scripts/sync_baseline.py`
(built on `scripts/render.py` and `scripts/stamp.py`). It re-renders the plugin's
current templates with the slot values recorded at stamp time and compares them
against what is on disk. This skill is the human-facing procedure that drives it.

Follow the steps in order.

## (0) Version-check preflight

<!-- BEGIN crow-mind-workflow version PREFLIGHT -->
> **Preflight — plugin version check.**
> Read `${CLAUDE_PLUGIN_DATA}/version-status.json`.
> - If `status == "behind"`, surface its `updateInstructions` to the user
>   **before** doing anything else, and let them decide whether to update first.
> - If the file is missing or `status == "unknown"`, run
>   `${CLAUDE_PLUGIN_ROOT}/scripts/check-version.sh` once to refresh it, then
>   re-read and apply the rule above.
> - If `status == "up-to-date"`, proceed silently.
>
> This is a non-blocking reminder: a stale or unreachable check never prevents
> the skill from running.
<!-- END crow-mind-workflow version PREFLIGHT -->

Updating the *plugin* (above) and updating the *repo's baseline* (this skill) are
different actions: even after the plugin is current, the target repo may still be
behind the templates and need the sync below.

## (1) Confirm the target repo

Ask for the **absolute path** of the stamped repo to check. The repo must already
carry `.claude/.workflow-baseline.json` (written by the init-repo skill). If it does
not, the script says so and exits — point the user at init-repo instead.

## (2) Report drift (read-only)

Run the reporter — this writes nothing:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sync_baseline.py" --target <repo>
```

Exit codes: **0** = in sync, **3** = drift found, **2** = error (repo not stamped /
bad manifest).

Present the categorized findings to the user in plain language:

- **behind** — the plugin's template changed since the stamp; the on-disk file is
  unmodified. *Safe to update.*
- **locally modified** — the user hand-edited a stamped file (the template did not
  change). Updating would discard their edit, so it is **left alone** unless they
  opt into `--force`.
- **conflict** — the user edited the file **and** the template changed. Needs a
  manual merge; also protected from clobbering unless `--force`.
- **missing** — a recorded file is gone from disk; `--apply` restores it.
- **new templates** — templates the plugin added since the stamp; `--apply` stamps
  them in.
- **slots** — `new` (plugin added a slot to fill via init-repo), `unfilled` (an
  empty recorded value), `stale` (a recorded slot the plugin no longer defines).
- **version** — whether the stamp trails the installed plugin version.

If a template now needs a slot the stamp never recorded, the report flags it as
**needs re-init** — that file cannot be re-rendered cleanly here; re-run init-repo to
collect the new slot.

## (3) Update — only with explicit approval

Updating rewrites governance files and the baseline manifest, so **get explicit
approval before running `--apply`.** Present it as an approval request (system:
crow-mind-workflow baseline; target: the repo; proposed change: update the
behind/new/missing files and bump the manifest; reason: bring the repo current with
the plugin). Only on a clear "yes":

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sync_baseline.py" --target <repo> --apply
```

`--apply` updates **behind** files, restores **missing** files, stamps in **new
templates**, and refreshes the manifest (recomputed hashes, new entries, the plugin
version bumped, `stampedAt` restamped). It **skips locally-modified and conflicting
files** and lists them as needing manual attention — the user's edits are preserved.

If the user has reviewed those skipped files and truly wants them overwritten with
the plugin's version (losing their edits), and only after a second explicit
approval, add `--force`:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/sync_baseline.py" --target <repo> --apply --force
```

Explain plainly that `--force` **discards the user's local edits** to those files.

## (4) Report back

Tell the user what changed — the updated / restored / added file lists from the
`--apply` output — which files were **skipped** (edits preserved) and why, any
**needs re-init** slots, and that the baseline manifest was refreshed at
`<repo>/.claude/.workflow-baseline.json`. If slots are new or unfilled, point them at
the init-repo skill to collect the missing values.
