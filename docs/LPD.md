# LPD — crow-mind-workflow: package the governance workflow as an installable plugin

> **Linear Planning Document.** Input to the **`wave-plan`** skill: it describes
> the goal, the discrete vertical slices, and their dependencies so they can be
> layered into parallelizable execution waves (→ `docs/wave.yml` + a Linear
> parent issue with one sub-issue per wave ticket).

- **Tags:** `TEAM = CRO` · `PROJECT = crow-mind-workflow` (Linear project
  defaults to *Init Team* per the default-project convention — change if a
  dedicated project is created).
- **This repo (build target):** `https://github.com/wesduffdev/claude_workflow.git`
- **Workflow source of truth:** the `oodo-agent` repo — its `CLAUDE.md`,
  `.claude/{rules,agents,skills,hooks,settings.json}`, and `.githooks/`. Those
  files are the material this plugin generalizes into templates.

---

## Goal

Ship **`crow-mind-workflow`** — a Claude Code plugin (hosted in the **`crow-mind`**
marketplace in this repo) that packages the `oodo-agent` engineering-governance
workflow as **reusable, parameterized templates**. In one sentence:

> A user adds the marketplace, installs the plugin, runs **`init-repo`** to stamp
> any repository with the workflow (CLAUDE.md, `.claude/` rules + agents + skills
> + hooks + settings, `.githooks/`), keeps a stamped repo current with
> **`sync-baseline`**, is reminded to update whenever the plugin's skills/tools
> are used, and — when the target repo's GitHub Wiki is available — has its Wiki
> **Workflow** page created/updated automatically during stamping.

The workflow being packaged is deliberately generic governance (worktree → PR,
Linear vertical-slice ticketing, the MCP **Tool Gateway**, wave planning, Wiki
docs) — the Odoo/Linear-specific values become **interview-filled slots**, not
hardcoded strings.

## Why (background)

The `oodo-agent` repo carries a complete, opinionated workflow: never commit to
`main`; every task in a `git worktree` on a feature branch; every change traces
to a Linear ticket; MCP flows only through narrow specialist agents behind a Tool
Gateway; all prose docs live in the Wiki with a living **Workflow** page. Today
that only benefits that one repo. Packaging it as a plugin lets us stamp the same
workflow onto *any* repo in seconds and keep every stamped repo in sync as the
workflow evolves.

## Requirements (from the request) → where each is delivered

| # | Requirement | Slice |
|---|-------------|-------|
| 1 | A **marketplace** with a copy-paste install command | **S1** |
| 2 | **Check for version bumps** every time a skill / tool / plugin is used | **S4** |
| 3 | On a bump, **provide update instructions** | **S4** |
| 4 | **`init-repo`** skill stamps `CLAUDE.md`, `.claude/` (rules, hooks, tools, agents…), everything needed to run the workflow | **S3** (content from **S2**) |
| 5 | Stamping **checks GitHub Wiki availability**; if available, updates the Wiki incl. a **`Workflow`** page (as in the source repo) | **S5** (dogfooded in **S7**) |
| 6 | **`sync-baseline`** skill updates a stamped repo with what changed between the stamp origin and the repo | **S6** |

> Note on "tools": in this workflow **tools** means the **Tool Gateway policy** —
> `.claude/settings.json` permissions (reads allow / writes ask / `delete_*` deny)
> plus each specialist agent's narrow `tools:` allow-list. It is stamped as part
> of `.claude/` (S2/S3), not as standalone tool files.

---

## Design decisions & assumptions

- **Stamp mode = parameterized (interview).** `init-repo` prompts for
  repo-specific values and fills `{{SLOT}}` placeholders in the templates, so the
  workflow is reusable across any repo. *(Confirmed with the requester.)*
- **Names** (low-stakes, easily changed — see Open Questions):
  - marketplace **`crow-mind`**, plugin **`crow-mind-workflow`**.
  - install: `/plugin marketplace add wesduffdev/claude_workflow` then
    `/plugin install crow-mind-workflow@crow-mind`.
  - skills are namespaced `/crow-mind-workflow:init-repo`,
    `/crow-mind-workflow:sync-baseline`, `/crow-mind-workflow:version-check`.
- **Repo layout** (per the Claude Code plugin spec — component dirs live at the
  plugin root, only `plugin.json` under `.claude-plugin/`):
  ```
  claude_workflow/                            # marketplace repo root
    .claude-plugin/marketplace.json           # marketplace "crow-mind" lists the plugin
    plugins/crow-mind-workflow/
      .claude-plugin/plugin.json              # name, version (bump per release), author
      skills/{init-repo,sync-baseline,version-check}/SKILL.md
      hooks/hooks.json + scripts/             # SessionStart version check
      templates/                              # the parameterized workflow to stamp
        CLAUDE.md, README-governance.md, pull_request_template.md
        .claude/{rules,agents,skills,hooks,settings.json}
        .githooks/{pre-commit,pre-push}
        slots.yml                             # slot definitions (prompt/default/validation)
        baseline-manifest.schema.json         # shape of the per-repo stamp record
    README.md                                 # copy-paste install command + usage
  ```
- **The plugin's own active skills are only** `init-repo`, `sync-baseline`, and
  `version-check`. The workflow skills (`worktree-pr-workflow`, `wiki-docs`,
  `wave-plan`, `linear-ticket-workflow`, `swagger-docs`) travel as **templates**
  that get stamped into each target repo's `.claude/skills/`, so a stamped repo is
  self-contained and works for teammates who don't have the plugin installed.
- **Slots** (initial set): `PROJECT_NAME`, `PROJECT_DESC`, `GH_OWNER`, `GH_REPO`,
  `WIKI_URL`, `LINEAR_TEAM`, `DEFAULT_PROJECT`, `MCP_SERVER`, `BUILD_CMD`,
  `TEST_CMD`, `CONNECTIVITY_CMD`.
- **Baseline manifest** (`.claude/.workflow-baseline.json`, written by `init-repo`):
  records the stamped plugin version, the template-set version, and per-file
  `{source-template, rendered-hash, slot-values}`. This is what `sync-baseline`
  diffs against.
- **Version-check cadence:** the network fetch runs once per session
  (`SessionStart` hook) and caches its verdict to `${CLAUDE_PLUGIN_DATA}`; the
  three skills read that cache on each invocation so the "every time a skill/tool
  is used" reminder is cheap (no per-call network hit). Update instructions name
  `/plugin marketplace update crow-mind` + `/plugin update crow-mind-workflow@crow-mind`.
- **Governance for building this repo itself:** `claude_workflow` is developed
  under the same rules (worktree → PR, Linear ticket per slice, no direct commits
  to `main`) and dogfoods its own workflow in S7.

## Non-goals (out of scope for this plan)

- No new MCP servers beyond the parameterized `linear-personal` reference.
- No hosted service / web UI — distribution is a GitHub repo marketplace only.
- No automatic mutation of a stamped repo's application code — `init-repo` only
  writes governance files (`CLAUDE.md`, `.claude/`, `.githooks/`, PR template,
  README governance index).
- Migrating `oodo-agent` itself onto the plugin is a later effort, not part of
  this plan.

---

## Vertical slices (the units `wave-plan` will layer)

Each slice is a complete, shippable slice of behavior with an explicit dependency
list (`dependsOn` = slices that must finish first).

### S1 — Marketplace & installable plugin shell
**Delivers:** a marketplace a user can add and install from, even before it does
much. `.claude-plugin/marketplace.json` (marketplace `crow-mind`);
`plugins/crow-mind-workflow/.claude-plugin/plugin.json` (name `crow-mind-workflow`,
`version 0.1.0`, author/repo/license); root `README.md` with the copy-paste
**install command block**; a CI check running `claude plugin validate .` on PRs.
**Done when:** `/plugin marketplace add wesduffdev/claude_workflow` +
`/plugin install crow-mind-workflow@crow-mind` succeeds against the repo.
**dependsOn:** _(none)_

### S2 — Parameterized baseline templates + slot scheme + manifest schema
**Delivers:** the whole workflow ported into `plugins/crow-mind-workflow/templates/`
with `{{SLOT}}` placeholders — `CLAUDE.md`, `.claude/rules/*`, `.claude/agents/*`,
the five workflow skills, `.claude/hooks/*` + `settings.json`, `.githooks/*`, a
README governance index, and a PR template. Plus `slots.yml` (each slot's key,
prompt, default, validation) and `baseline-manifest.schema.json`.
**Done when:** rendering the templates with a sample slot set produces a coherent,
valid `.claude/` tree (dry-run render test passes) with no leftover placeholders.
**dependsOn:** _(none)_

### S3 — `init-repo` skill (the stamper)
**Delivers:** `plugins/crow-mind-workflow/skills/init-repo/SKILL.md` (+ helper
script). Asks root vs. nested/monorepo stamp; interviews for the S2 slots; renders
the templates into the target repo (`CLAUDE.md`,
`.claude/{rules,agents,skills,hooks,settings.json}`, `.githooks/`, README
governance pointer, PR template); writes the baseline manifest (S2 schema)
recording plugin version + slot values + file hashes; prints the
`git config core.hooksPath .githooks` enablement step; safe/idempotent on re-run
(detects an existing stamp).
**Done when:** running `init-repo` in a scratch repo yields a fully-stamped,
placeholder-free governance tree recorded in a manifest.
**dependsOn:** S1, S2

### S4 — Version-check mechanism (hook + skill)
**Delivers:** `plugins/crow-mind-workflow/hooks/hooks.json` with a `SessionStart`
hook → `scripts/check-version.sh` that fetches the published `marketplace.json`,
compares to the installed `plugin.json` version, caches the verdict to
`${CLAUDE_PLUGIN_DATA}/version-status.json`, and emits a `systemMessage` with
update instructions when behind. A `version-check` skill (and a small preflight
the three skills call) reads the cached verdict so **every** skill/tool use
surfaces the reminder without re-fetching.
**Done when:** with `plugin.json` behind the published `marketplace.json`, a fresh
session (and any subsequent skill run) shows the update instructions; when equal,
it is silent.
**dependsOn:** S1

### S5 — Wiki publish on stamp (the `Workflow` page)
**Delivers:** extends `init-repo` to detect whether the target repo's GitHub Wiki
is available (`git ls-remote <owner>/<repo>.wiki.git`). If available: clone it,
render/update `Workflow.md` from a template (mirroring the source repo's Workflow
page), commit and push; also seed `Home.md`/`_Sidebar.md` if empty. If
unavailable: skip gracefully with a clear note on how to enable the Wiki once in
the GitHub UI. Uses the `WIKI_URL`/`GH_*` slots from S2.
**Done when:** stamping a repo whose Wiki exists produces/updates a `Workflow`
page; stamping one without a Wiki skips with guidance (no failure).
**dependsOn:** S3

### S6 — `sync-baseline` skill (drift + update)
**Delivers:** `plugins/crow-mind-workflow/skills/sync-baseline/SKILL.md` (+ helper).
Reads the repo's baseline manifest (S3), re-renders each template with the recorded
slot values (S2), and reports **drift**: files behind the current templates, files
modified locally (conflict), templates added since the stamp, unfilled/renamed
slots, and whether the recorded plugin version trails the installed one. An
approval-gated update applies the newer baseline and bumps the manifest's recorded
version.
**Done when:** given a repo stamped at `vN` and a plugin at `vN+1` with a changed
rule, `sync-baseline` reports the drift and can update the stamped files on
approval.
**dependsOn:** S2, S3

### S7 — End-to-end docs, Wiki dogfood & walkthrough
**Delivers:** the full root README (marketplace overview, plugin usage, skill
catalog, update flow) and plugin README; **dogfoods requirement #5** by publishing
`claude_workflow`'s *own* GitHub Wiki with a `Workflow` page; and a documented
end-to-end walkthrough test: marketplace add → install → `init-repo` on a sample
repo → verify Wiki page → bump version → confirm the version-check surfaces →
`sync-baseline` updates.
**Done when:** a new user can, from the README alone, install and stamp a repo, and
the `claude_workflow` repo's own Wiki has a `Workflow` page.
**dependsOn:** S3, S4, S5, S6

---

## Suggested wave layering (authoritative plan comes from `wave-plan` → `docs/wave.yml`)

| Wave | Slices (mutually independent → run in parallel) |
|------|--------------------------------------------------|
| **1** | **S1** (marketplace shell) · **S2** (templates + slots + manifest schema) |
| **2** | **S3** (init-repo) ← S1,S2 · **S4** (version check) ← S1 |
| **3** | **S5** (wiki-on-stamp) ← S3 · **S6** (sync-baseline) ← S2,S3 |
| **4** | **S7** (docs + wiki dogfood + e2e walkthrough) ← S3,S4,S5,S6 |

## Open questions (resolve during planning, don't block wave layering)

1. **Names** — confirm marketplace `crow-mind` / plugin `crow-mind-workflow`
   (install `crow-mind-workflow@crow-mind`), or flip (e.g. marketplace
   `crow-mind-workflow` / plugin `workflow` → `workflow@crow-mind-workflow`). This
   only changes strings in S1/S4/S7.
2. **Dedicated Linear project** — keep the default *Init Team* project, or create a
   `crow-mind-workflow` project for these tickets?
3. **Version pinning** — set `version` in `plugin.json` and bump per release
   (chosen), vs. omit it and use commit SHA. S4 assumes an explicit version string.
