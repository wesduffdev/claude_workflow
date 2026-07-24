---
name: worktree-pr-workflow
description: The mandatory workflow for ALL changes in this repo — create a git worktree on a feature branch, do the work there, and deliver a Pull Request for human approval. Never commit to main. Use at the start of any task and when preparing to open a PR.
---

# Worktree → work → PR

This repo has a hard rule: **`main` is never committed to directly.** Every
change is done in an isolated `git worktree` on a feature branch and delivered
as a PR that a human approves and merges. This skill is the exact procedure.

## Who does what

- The **Orchestrator** (top-level session) runs the worktree lifecycle, the
  push, and the PR. It is the only one that talks to GitHub, via the `gh` CLI
  (GitHub is not an MCP tool in this repo).
- **Sub-agents** work *inside* the worktree path they are given. They may commit
  within the worktree but do not push or open PRs.

## 0. Mint the Linear ticket (Orchestrator)

**No PR without a ticket.** Before starting, ensure a Linear **vertical-slice**
ticket exists in `{{MCP_SERVER}}` for the change — delegate to
[`linear-ticket-agent`](../../agents/linear-ticket-agent.md) to mint one
(`save_issue`, approval-gated). Note the ticket id; the PR will link it. See
[`ticketing`](../../rules/ticketing.md).

## 1. Create the worktree (Orchestrator)

Pick a short branch name: `feat/…`, `fix/…`, `chore/…`, `docs/…`.

```bash
git fetch origin
BRANCH=feat/short-description
WT="../worktrees/${BRANCH//\//-}"     # e.g. ../worktrees/feat-short-description
git worktree add "$WT" -b "$BRANCH" origin/main
```

Worktrees live in a sibling `../worktrees/` directory so they never nest inside
the primary checkout. Hand the **absolute** `$WT` path to every sub-agent.

## 2. Do the work (delegated to sub-agents)

Follow the standard workflow in `CLAUDE.md`: tests first (`test-engineer`),
implement (`engineer`), docs (`doc-writer`), review (`reviewer`). All edits
happen under `$WT`.

## 3. Commit (inside the worktree)

The `.githooks/pre-commit` hook refuses commits on `main`; enable it once per
clone with `git config core.hooksPath .githooks`.

```bash
git -C "$WT" add -A
git -C "$WT" commit -m "feat: short description of the change"
```

Write a clear, imperative commit subject; explain *why* in the body when it
isn't obvious.

## 4. Verify before pushing

```bash
git -C "$WT" status
{{TEST_CMD}}   # run the test suite from within $WT
```

## 5. Push and open the PR (Orchestrator)

```bash
git -C "$WT" push -u origin "$BRANCH"
gh pr create --base main --head "$BRANCH" \
  --title "…" --body "…"     # fill in from the PR template
```

The PR **is the report back**. Fill in the repository PR template
(`.github/pull_request_template.md`): the **Linear ticket** it delivers, summary,
changes, how it was built (orchestrator + specialists), testing, and Wiki doc
links. If the workflow itself changed, update the **[[Workflow]]** wiki page in the
same change. Then hand the PR URL to the human. **Do not merge** — approval is a
human step.

## 6. Clean up after merge

Once a human has merged the PR:

```bash
git worktree remove "$WT"
git branch -d "$BRANCH"      # local
```

## Rules recap

- No PR without a Linear vertical-slice ticket; the PR links it.
- Never `git commit` or `git push` on `main`.
- One worktree per task; remove it when the PR merges.
- Sub-agents never push and never open/merge PRs.
