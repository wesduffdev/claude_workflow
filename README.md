# Crow Mind

Crow Mind packages a reusable engineering-governance workflow as an installable
Claude Code plugin. Add the marketplace, install the plugin, and run **`init-repo`**
to *stamp* any repository with the workflow — `CLAUDE.md`, the `.claude/` Tool-Gateway
layout (rules, agents, skills, hooks, settings), guard git hooks, a README governance
index, and a PR template — plus, when the repo's GitHub Wiki is available, a living
**Workflow** page. **`sync-baseline`** keeps a stamped repo current as the baseline
evolves, and **`version-check`** tells you when a newer plugin release is published.

## Install

```
/plugin marketplace add wesduffdev/claude_workflow
/plugin install crow-mind-workflow@crow-mind
```

## The workflow it stamps

The stamped baseline is deliberately generic governance — repo-specific details
(project name, GitHub owner/repo, Linear team, MCP server, build/test commands) are
filled from an interview, not hardcoded. In one paragraph:

> `main` is never committed to directly — it advances only through a human-approved
> PR. Every task runs in its own `git worktree` on a feature branch. Every change
> traces to a Linear **vertical-slice** ticket, and the PR links it. External systems
> are reached only through narrow **specialist agents** behind an MCP **Tool Gateway**
> (deny-by-default; reads automatic, writes human-approved, destructive ops denied).
> All prose documentation lives in the Wiki, whose **Workflow** page is kept in sync
> with the rules.

## Skill catalog

The plugin ships three skills (namespaced `crow-mind-workflow:<skill>`):

- **`init-repo`** — the stamper. Interviews for the repo's slot values, previews the
  stamp with a dry-run, then renders the baseline into the target repo and writes a
  **baseline manifest** (`.claude/.workflow-baseline.json`) recording the plugin
  version, slot values, and a content hash of every stamped file. Asks root vs. nested
  (monorepo sub-app) placement, is idempotent (refuses to clobber an existing stamp
  without `--force`), and after a successful stamp offers to publish the Wiki
  **Workflow** page (approval-gated).
- **`sync-baseline`** — the reconciler. Re-renders the plugin's *current* templates
  with the slot values recorded at stamp time and compares them to what is on disk,
  reporting drift by category: **behind** (plugin template moved on), **locally
  modified** / **conflict** (your edits — never clobbered without `--force`),
  **missing**, brand-new templates, unfilled/renamed slots, and whether the stamp
  trails the installed plugin version. An **approval-gated** `--apply` updates the safe
  files and refreshes the manifest.
- **`version-check`** — the updater's radar. Reads a cache written by the plugin's
  `SessionStart` hook and reports whether the installed plugin is current with the
  published marketplace, surfacing the exact update commands when it is behind.

## Stamping a repo (`init-repo`)

1. **Interview.** `init-repo` reads `templates/slots.yml` and asks for each slot
   (project name/description, GitHub owner/repo, Wiki URLs, Linear team + default
   project, MCP server name, build/test/connectivity commands, a short repo map). It
   confirms the collected values with you.
2. **Dry-run preview.** It renders into a throwaway directory and shows the exact file
   list — nothing is written to the target yet.
3. **Stamp.** On your go-ahead it renders the baseline into the target repo and writes
   the baseline manifest. Re-stamping an already-stamped repo requires `--force`.
4. **Enable the guard hooks** (one-time, in the target repo — blocks commits/pushes to
   `main`):

   ```bash
   git config core.hooksPath .githooks
   ```

5. **Publish the Wiki (optional, approval-gated).** If the repo's GitHub Wiki is
   initialized, `init-repo` offers to publish the **Workflow** page (seeding `Home`
   and `_Sidebar` only if absent). Publishing is a protected write, so it happens only
   after you review the full rendered page and confirm. If the Wiki is not yet
   initialized, it prints enable-it guidance and skips gracefully — the stamp still
   succeeded.

Only governance files are written — never application code. If the repo already has a
`README.md` or `.github/pull_request_template.md`, the crow-mind versions land beside
them (`README-governance.md`, `pull_request_template.crow-mind.md`) instead of
clobbering yours.

## Keeping a stamped repo current (`sync-baseline`)

As the plugin's baseline evolves, run `sync-baseline` against a stamped repo to see
what drifted. It is **report-only by default** (exit `0` = in sync, `3` = drift). The
repair step (`--apply`) is **approval-gated** and updates only the safe categories
(behind / missing / new templates) while leaving your hand-edits untouched unless you
explicitly opt into `--force`.

## Updates (`version-check`)

On session start the plugin's hook fetches the published `marketplace.json`, compares
its `crow-mind-workflow` version to the installed one, caches the verdict, and — only
when behind — surfaces update instructions. Every later skill/tool use reads that
cache, so the reminder re-appears without another network call. To update:

```
/plugin marketplace update crow-mind
/plugin update crow-mind-workflow@crow-mind
```

## Versioning

The plugin version lives in two places that are **bumped together per release**:

- `plugins/crow-mind-workflow/.claude-plugin/plugin.json` — the installed version.
- `.claude-plugin/marketplace.json` (the plugin entry) — the "latest published"
  signal `version-check` reads to detect updates.

Keep these two identical. CI (`.github/workflows/validate.yml`) fails the build if
they drift.

## Repo layout

```
claude_workflow/
  .claude-plugin/marketplace.json          the crow-mind marketplace (lists the plugin)
  plugins/crow-mind-workflow/
    .claude-plugin/plugin.json             name + version (bumped per release)
    README.md                              plugin-level reference
    skills/{init-repo,sync-baseline,version-check}/SKILL.md
    templates/                             the parameterized governance baseline to stamp
      CLAUDE.md, README-governance.md, pull_request_template.md, slots.yml
      .claude/{rules,agents,skills,hooks,settings.json}, .githooks/
    wiki-templates/                        Workflow / Home / _Sidebar wiki pages
    scripts/                               render, stamp, sync_baseline, publish_wiki,
                                           check-version, e2e_test.sh
    hooks/hooks.json                       SessionStart version check
    baseline-manifest.schema.json          shape of the per-repo stamp record
  docs/                                    planning + the end-to-end walkthrough
  .github/workflows/validate.yml           CI: manifest + version-parity checks
```

## Planning & walkthrough

- [`docs/LPD.md`](docs/LPD.md) — the Linear Planning Document for this plugin.
- [`docs/wave.yml`](docs/wave.yml) — the dependency-layered execution waves.
- [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md) — the end-to-end walkthrough (install →
  stamp → verify → update → sync → Wiki), backed by the runnable
  `plugins/crow-mind-workflow/scripts/e2e_test.sh`.
