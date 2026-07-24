---
name: wiki-docs
description: How documentation is authored and published for this repo. ALL prose documentation lives in the GitHub Wiki, not the repo. Sub-agents author markdown content; only the Orchestrator publishes it to the Wiki (a separate git repo). Use when creating or updating any documentation.
---

# Documentation lives in the Wiki

Repo rule: **all documentation goes in the [Wiki]({{WIKI_URL}}).**
The repository itself keeps only `CLAUDE.md`, a simple root `README.md`, and
inline code docs. Do not add `docs/` prose or long guides to the repo tree.

The GitHub Wiki is its own git repository:
`{{WIKI_GIT_URL}}`.

## Division of labor

- **Sub-agents (e.g. `doc-writer`) author content only.** They write markdown
  and hand it to the Orchestrator. They **never** connect to MCP and **never**
  push to the Wiki repo.
- **The Orchestrator publishes.** It clones the Wiki repo, adds/updates pages,
  commits, and pushes — via `git`/`gh` (GitHub is not an MCP tool in this repo).

## Authoring conventions

- One page per topic. Page file name = page title with spaces → hyphens, e.g.
  `Architecture.md`, `Local-Setup.md`, `Running-in-CI.md`, `API-Reference.md`.
- `Home.md` is the landing page: what the project is + a short table of contents.
- `_Sidebar.md` lists the pages for navigation.
- Plain language first. Link between pages with `[[Page-Name]]` wiki links.
- Keep code snippets runnable and current.

## Publishing procedure (Orchestrator only)

```bash
# Clone the wiki repo (separate from the code repo)
git clone {{WIKI_GIT_URL}} /tmp/{{GH_REPO}}-wiki

# Drop in / update the authored pages
cp wiki-drafts/*.md /tmp/{{GH_REPO}}-wiki/

# Commit and push
git -C /tmp/{{GH_REPO}}-wiki add -A
git -C /tmp/{{GH_REPO}}-wiki commit -m "docs: <what changed>"
git -C /tmp/{{GH_REPO}}-wiki push
```

If the clone fails because the Wiki has never been initialized, a human must
enable **Wiki** in the repo settings and create the first page once in the
GitHub UI; after that the `.wiki.git` repo exists and the procedure above works.

## Keep the Workflow page in sync

The Wiki's **Workflow** page is the living description of how work is done in this
repo. **Whenever the workflow changes** — `CLAUDE.md`, `.claude/rules/`, agents,
skills, `.claude/settings.json`, or the worktree → PR process — the *same change*
must **update the Workflow wiki page** so the two never drift. The `doc-writer`
authors the update; the Orchestrator publishes it.

## What goes where

| Content | Location |
|---------|----------|
| What the repo does (short) | root `README.md` |
| Engineering rules / agent + skill index | `CLAUDE.md` |
| How the workflow is used (living page) | **Wiki → [[Workflow]]** |
| Architecture, runbooks, how-tos, API reference, deep guides | **Wiki** |
| Why a comment / decision, at the code level | inline code docs |
