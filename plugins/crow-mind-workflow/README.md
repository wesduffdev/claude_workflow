# crow-mind-workflow

The installable plugin behind the [crow-mind](../../README.md) marketplace. It stamps
the crow-mind engineering-governance workflow into any repository, keeps a stamped repo
in sync as the baseline evolves, and reminds you when a newer release is published.

Install from the marketplace repo:

```
/plugin marketplace add wesduffdev/claude_workflow
/plugin install crow-mind-workflow@crow-mind
```

This page is the plugin-level reference. For the end-user narrative see the root
[`README.md`](../../README.md); for the full documented run see
[`docs/WALKTHROUGH.md`](../../docs/WALKTHROUGH.md).

## Skills

Three user-invocable skills (namespaced `crow-mind-workflow:<skill>`):

| Skill | Purpose |
|-------|---------|
| [`init-repo`](skills/init-repo/SKILL.md) | Interview → dry-run → stamp the governance baseline into a target repo, write the baseline manifest, and (approval-gated) publish the Wiki Workflow page. |
| [`sync-baseline`](skills/sync-baseline/SKILL.md) | Report how a stamped repo has drifted from the plugin's current templates, and — approval-gated — update the safe files without clobbering local edits. |
| [`version-check`](skills/version-check/SKILL.md) | Report whether the installed plugin is current with the published marketplace and surface the update commands when behind. |

`init-repo` and `sync-baseline` both begin with a version-check **preflight** so any
pending plugin update surfaces before a governance action runs.

## Templates + slots

`templates/` holds the parameterized workflow that gets stamped into a target repo:
`CLAUDE.md`, `README-governance.md`, `pull_request_template.md`, the
`.claude/{rules,agents,skills,hooks,settings.json}` Tool-Gateway layout, and the
`.githooks/` guard hooks. Every repo-specific value is a `{{SLOT}}` placeholder.

`templates/slots.yml` is the slot catalog the `init-repo` interview reads — each entry
carries a `key`, `prompt`, `default`, `required` flag, and `example`. It is **metadata**:
the render engine skips it, so it is never stamped into a target repo. The current slots
are `PROJECT_NAME`, `PROJECT_DESC`, `GH_OWNER`, `GH_REPO`, `WIKI_URL`, `WIKI_GIT_URL`,
`MCP_SERVER`, `LINEAR_TEAM`, `DEFAULT_PROJECT`, `BUILD_CMD`, `TEST_CMD`,
`CONNECTIVITY_CMD` (optional), and `REPO_MAP`.

`wiki-templates/` holds the pages published to the target repo's **Wiki** — `Workflow.md`
(always re-published), `Home.md`, `_Sidebar.md` (seeded only if absent). These are kept
out of `templates/` on purpose so `stamp.py` never lays them into the working tree.

## Engine scripts

The skills are thin human-facing procedures; the mechanics live in dependency-free
Python 3 (stdlib only) plus one bash hook under `scripts/`. Each has a `--self-test`
that runs offline and prints a PASS/FAIL summary.

| Script | Responsibility | Self-test |
|--------|----------------|-----------|
| `render.py` | The substitution primitive: copy a template tree to an output dir, replacing every `{{KEY}}`, preserving exec bits, failing on any leftover placeholder. Everything else reuses it. | `render.py --self-test` — renders `templates/` with `sample-slots.json`; asserts no `{{`, valid JSON, no source-specific literal leaks. |
| `stamp.py` | The placement layer on `render`: lay the rendered tree into the right spots in a target repo (root vs. nested), handle the PR-template collision and empty-`CONNECTIVITY_CMD` strip, and write the baseline manifest. | `stamp.py --self-test` — stamps into temp targets; asserts a coherent tree, a schema-valid manifest, and a placement-stable `--force` re-stamp. |
| `sync_baseline.py` | The reconciler on `render` + `stamp`: re-render current templates with the recorded slots and classify each file as in-sync / behind / local-modification / conflict / missing / obsolete; `--apply` repairs the safe categories. | `sync_baseline.py --self-test` — drives template drift, local edits, slot drift, a new template, a relocated PR template, and a version-behind manifest. |
| `publish_wiki.py` | Publish the **Workflow** page to the repo's GitHub Wiki. Availability probe and clone are injectable seams so the flow is testable with no network; publishing is gated (`--push` only after confirmation, `--dry-run` forces no-push). | `publish_wiki.py --self-test` — renders the pages and exercises the unavailable / available / seed-if-absent branches with stubbed git. |
| `check-version.sh` | The `SessionStart` hook: fetch the published `marketplace.json`, compare to the installed version, cache the verdict, and emit a `systemMessage` only when behind. Defensive — any failure degrades to `unknown`, stays silent, and exits 0. | `check-version.sh --self-test` — exercises behind / up-to-date / offline (and outage-survives-prior-verdict) with no network. |
| `e2e_test.sh` | The end-to-end green bar: runs the real scripts against temp dirs to prove the whole chain (stamp → sync → version → wiki) fits together. | itself — `bash scripts/e2e_test.sh` exits 0 on success. |

`sample-slots.json` is the fixture the self-tests render with (a fictional
`acme-billing` repo, no real-repo values).

## Baseline manifest

Every stamp writes `.claude/.workflow-baseline.json` — the per-repo record
`sync-baseline` diffs against. It captures the `pluginName`, `pluginVersion`,
`templateSetVersion`, `stampedAt`, the `slots` used, and one `files` entry per stamped
file (`path`, source `template`, and content `sha256`). Its shape is defined and
enforced by [`baseline-manifest.schema.json`](baseline-manifest.schema.json); `stamp.py`
validates every manifest it writes against that schema.

## SessionStart hook

`hooks/hooks.json` wires `check-version.sh` to the `SessionStart` event. On each session
it refreshes the cache at `${CLAUDE_PLUGIN_DATA}/version-status.json` and surfaces the
update reminder when the install is behind. The three skills read that cache, so the
reminder is cheap to re-surface without re-fetching.

## Versioning

Bump the version in **both** `.claude-plugin/plugin.json` and the `crow-mind-workflow`
entry of the marketplace's `.claude-plugin/marketplace.json` **together** per release —
`plugin.json` is the installed version, the marketplace entry is the "latest published"
signal `check-version.sh` reads. CI (`.github/workflows/validate.yml`) fails if they
drift.
