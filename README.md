# Crow Mind

Crow Mind packages a reusable engineering-governance workflow as an installable
Claude Code plugin. It is designed so that an `init-repo` skill will stamp any
repository with the workflow, a `sync-baseline` skill will keep a stamped repo
current with the latest baseline, and a `version-check` will surface update
instructions when a newer release is published. When the target repo's GitHub
Wiki is available, stamping will also publish a **Workflow** page.

## Install

```
/plugin marketplace add wesduffdev/claude_workflow
/plugin install crow-mind-workflow@crow-mind
```

## What you get

Three skills ship with the plugin. They land in subsequent slices and are **not
present yet**:

- **`init-repo`** — stamps the governance workflow into a repository.
- **`sync-baseline`** — reports drift and updates a stamped repo to the current baseline.
- **`version-check`** — surfaces update instructions when a newer release is published.

## Versioning

The plugin version lives in two places that are bumped together per release:

- `plugins/crow-mind-workflow/.claude-plugin/plugin.json` — the installed version.
- `.claude-plugin/marketplace.json` (the plugin entry) — the "latest published"
  signal a later slice's `version-check` reads to detect updates.

Keep these two identical.

## Planning

- [`docs/LPD.md`](docs/LPD.md) — the Linear Planning Document for this plugin.
- [`docs/wave.yml`](docs/wave.yml) — the dependency-layered execution waves.
