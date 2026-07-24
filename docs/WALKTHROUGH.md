# End-to-end walkthrough

This walks the whole crow-mind-workflow chain from a fresh install to a stamped,
kept-in-sync repo with a published Wiki. It has two parts:

1. **Manual (in Claude Code)** — adding the marketplace and installing the plugin.
   These are `/plugin` slash commands run inside Claude Code and cannot be scripted.
2. **Scriptable chain** — stamp → verify → simulate an update → version-check surfaces
   → sync-baseline updates → Wiki publish. Every scriptable step is proven by
   [`plugins/crow-mind-workflow/scripts/e2e_test.sh`](../plugins/crow-mind-workflow/scripts/e2e_test.sh),
   which runs the **real** engine scripts against throwaway temp dirs.

Run the runnable proof any time:

```bash
bash plugins/crow-mind-workflow/scripts/e2e_test.sh
```

It prints a PASS/FAIL for each assertion, cleans up its temp dirs, and exits `0` only
when the whole chain is green.

---

## Part 1 — Install (manual, in Claude Code)

```
/plugin marketplace add wesduffdev/claude_workflow
/plugin install crow-mind-workflow@crow-mind
```

Adding the marketplace registers the `crow-mind` marketplace from this repo; installing
pulls in the `crow-mind-workflow` plugin with its three skills (`init-repo`,
`sync-baseline`, `version-check`) and the `SessionStart` version-check hook. From this
point the three skills are invocable as `/crow-mind-workflow:init-repo`, and so on.

You cannot script `/plugin` commands — they are Claude Code's own plugin manager. The
scriptable chain below exercises everything the skills drive under the hood.

---

## Part 2 — The scriptable chain

Each step names the skill you would run in Claude Code and the underlying script the
`e2e_test.sh` calls to prove it. All script paths are relative to
`plugins/crow-mind-workflow/scripts/`.

### Step 1 — Stamp a repo (`init-repo` → `stamp.py`)

In Claude Code you would run **`init-repo`**: it interviews you for the repo's slots,
previews the stamp with a `--dry-run`, then stamps for real. The engine call is:

```bash
python3 stamp.py --slots <values.json> --target <repo> --mode root
```

**Proven by e2e step (a):** after the stamp, the target repo has `CLAUDE.md`, the
`.claude/{rules,agents,skills,hooks}` directories plus `.claude/settings.json`, the
executable `.githooks/{pre-commit,pre-push}`, the PR template under `.github/`, and the
baseline manifest at `.claude/.workflow-baseline.json` — with **no `{{` placeholder**
anywhere in the tree.

The one-time guard-hook enablement in the stamped repo:

```bash
git config core.hooksPath .githooks
```

### Step 2 — Verify the stamp

The stamp is self-verifying: `stamp.py` validates the manifest it writes against
`baseline-manifest.schema.json` and refuses to report success if any placeholder
survived or a required file is missing. Running `sync-baseline` immediately after a
stamp reports **in sync** (exit `0`) — the baseline matches the plugin exactly.

### Step 3 — Simulate a plugin update

A real update is a new plugin release (a bumped `plugin.json` + marketplace entry) whose
templates have moved on from what your repo was stamped with. The e2e simulates that
without publishing a release: it rolls the manifest's recorded `pluginVersion` back and
makes one recorded file read as an older variant (whose hash matches the manifest, so it
classifies as **behind** — a plugin template that moved on — not a local edit).

**Proven by e2e step (b), first half:** this is the "your repo is now behind the plugin"
condition the next two steps resolve.

### Step 4 — `version-check` surfaces the update (`check-version.sh`)

On session start the plugin hook compares the installed version to the published
marketplace version and, when behind, surfaces:

```
/plugin marketplace update crow-mind
/plugin update crow-mind-workflow@crow-mind
```

**Proven by e2e step (c):** `check-version.sh --self-test` exercises the **behind**,
**up-to-date**, and **offline** verdicts (including that a known verdict survives a
network outage) with no network access.

### Step 5 — `sync-baseline` reports and repairs (`sync_baseline.py`)

In Claude Code you would run **`sync-baseline`**. It is report-only by default:

```bash
python3 sync_baseline.py --target <repo>          # exit 0 = in sync, 3 = drift
```

and repairs the safe categories only after approval:

```bash
python3 sync_baseline.py --target <repo> --apply  # updates behind/missing/new; bumps manifest
```

**Proven by e2e step (b), second half:** the report exits `3` and lists the behind file;
`--apply` re-renders it and bumps the manifest's version back to the installed one; a
re-run then reports **in sync** (exit `0`). Locally-modified files are never overwritten
without an explicit `--force`.

### Step 6 — Publish the Wiki Workflow page (`publish_wiki.py`)

After a successful stamp, `init-repo` offers to publish the living **Workflow** page to
the target repo's GitHub Wiki. Publishing is a protected write, so it is gated:

```bash
python3 publish_wiki.py --slots <values.json> --dry-run   # preview, never pushes
python3 publish_wiki.py --slots <values.json> --push      # publish, after confirmation
```

If the repo's Wiki is not yet initialized, the script prints enable-it guidance and
exits `0` (a graceful skip — not a failure). The **Workflow** page is always
re-published; `Home` and `_Sidebar` are seeded only if the Wiki lacks them.

**Proven by e2e step (d):** `publish_wiki.py --self-test` renders all three pages
cleanly and exercises the unavailable / available / seed-if-absent branches with stubbed
git — no network, clone, or push.

---

## Dogfooding this repo's own Wiki

This repo carries its own slot values at
[`docs/crow-mind-workflow.slots.json`](crow-mind-workflow.slots.json), so the plugin can
stamp/publish `claude_workflow` itself. To preview this repo's **Workflow** page:

```bash
python3 plugins/crow-mind-workflow/scripts/publish_wiki.py \
  --slots docs/crow-mind-workflow.slots.json --dry-run
```

If the `claude_workflow` Wiki is not yet initialized, the dry-run prints enable-it
guidance and exits `0`. Once the Wiki is enabled (turn on **Wiki** in the repo settings
and create the first page once in the GitHub UI), the same command previews the full
rendered Workflow page, and publishing it is a single confirmed `--push`:

```bash
python3 plugins/crow-mind-workflow/scripts/publish_wiki.py \
  --slots docs/crow-mind-workflow.slots.json --push
```

Publishing to the Wiki is approval-gated and is performed by the Orchestrator, not by a
sub-agent.
