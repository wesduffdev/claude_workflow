# CLAUDE.md

Operating manual for anyone (human or AI) doing engineering work in this
repository. Read this first. The rules below are **non-negotiable**.

---

## What this repo is

`{{PROJECT_NAME}}` is {{PROJECT_DESC}}.

Full documentation lives in the **[Wiki]({{WIKI_URL}})** — not in this repo.

---

## Golden rules (non-negotiable)

1. **Never commit or push to `main`.** `main` only ever advances through a
   human-approved Pull Request merge. There are no exceptions and no "just this
   once" direct commits.
2. **Every task starts in a `git worktree` on a feature branch.** Before *any*
   work begins, create a dedicated worktree (see the
   [`worktree-pr-workflow`](.claude/skills/worktree-pr-workflow/SKILL.md) skill).
   Work never happens in the primary checkout.
3. **Every change traces to a Linear ticket.** Before a PR is opened, a
   **vertical-slice ticket** must be minted in `{{MCP_SERVER}}` (via the
   [`linear-ticket-agent`](.claude/agents/linear-ticket-agent.md), approval-gated).
   **No PR without a ticket** — the PR links its ticket. See
   [`.claude/rules/ticketing.md`](.claude/rules/ticketing.md).
4. **Deliver work as a Pull Request — the PR is the report back.** The PR is how
   a human reviews and approves the effort. **Never self-merge.**
5. **MCP flows through narrow specialist agents — never the Orchestrator.** MCP
   access is handled as a **Tool Gateway** (see
   [`.claude/rules/tool-gateway.md`](.claude/rules/tool-gateway.md)): the
   Orchestrator coordinates and holds *no* business-system MCP tools or
   credentials; each external system is reached only by a purpose-built
   **specialist agent** with a narrow, task-scoped `tools:` allow-list. Policy is
   deny-by-default; **reads are automatic, writes require per-action human
   approval, destructive ops are denied** (`.claude/settings.json`). GitHub stays
   on the `gh` CLI (not MCP).
6. **All documentation goes in the Wiki.** The repository holds only this
   `CLAUDE.md`, a deliberately simple root `README.md`, and inline code docs.
   Everything else — architecture, runbooks, API references, how-tos — lives in
   the [Wiki]({{WIKI_URL}})
   (see the [`wiki-docs`](.claude/skills/wiki-docs/SKILL.md) skill). The
   **[[Workflow]]** page is kept in sync whenever the workflow changes.
7. **Keep the root `README.md` simple.** It is a plain-language description of
   what this repo does plus pointers to the Wiki and this file. Deep content
   does not belong there.

---

## Engineering standards

- **Deep modules.** Prefer modules with a small, simple interface that hides
  substantial implementation (Ousterhout). A class like `ApiClient` should
  expose a handful of intention-revealing methods and hide transport, auth
  caching, and fault translation behind them. Push complexity *down* into the
  module; keep callers shallow. See the `codebase-design` skill when available.
- **Clean Code.** Small, single-purpose functions; intention-revealing names;
  no dead code; errors handled where they can be understood; comments explain
  *why*, not *what*. Match the style already in the file you are editing.
- **Design patterns (Gang of Four) when they genuinely simplify.** Reach for a
  pattern (Strategy, Adapter, Factory, Facade, etc.) when it removes duplication
  or clarifies a seam — never to show it off. A pattern that adds indirection
  without removing complexity is a defect.
- **REST APIs must ship Swagger / OpenAPI docs.** Any REST endpoint added to
  this repo is documented with an OpenAPI (Swagger) spec, served and kept in
  sync with the code (see the
  [`swagger-docs`](.claude/skills/swagger-docs/SKILL.md) skill). *(This rule
  applies the moment a REST API is introduced.)*
- **Test-Driven Development.** Write the failing test first, make it pass, then
  refactor (red → green → refactor). Use the `tdd` skill when available. Tests
  must pass before a PR is opened.

---

## The Orchestrator

The **top-level Claude session is the Orchestrator.** It coordinates; it does
not do the hands-on implementation itself. Its responsibilities:

- **Plan & decompose** the task into units of work.
- **Own the worktree lifecycle** — create the worktree/branch, keep it healthy,
  push it, and open the PR.
- **Own NO business-system MCP connection.** Delegate Linear work to the
  [`linear-ticket-agent`](.claude/agents/linear-ticket-agent.md); use `gh`/git for
  GitHub, PRs, and Wiki publishing. Do not call `mcp__{{MCP_SERVER}}__*` directly.
  Route human approvals for specialist writes and record results. (Full contract:
  [`.claude/agents/orchestrator.md`](.claude/agents/orchestrator.md).)
- **Delegate to specialists** by handing each a task package **and the absolute
  path of the worktree** to operate in — objective, scope, identifiers, permitted
  tools, prohibited actions, expected output, completion criteria (see
  [`.claude/rules/orchestration.md`](.claude/rules/orchestration.md)).
- **Integrate & verify** — collect sub-agent output, run the test suite, request
  a review pass, and only then open the PR.

The Orchestrator does **not** merge. A human approves and merges.

---

## Sub-agents

Defined in `.claude/agents/`. **Non-specialist sub-agents are MCP-free** (their
`tools:` lists contain no MCP tools). **Specialist agents** receive a narrow MCP
allow-list scoped to a single system (deny-by-default; see
[`.claude/rules/tool-gateway.md`](.claude/rules/tool-gateway.md)). Each has the
**`Skill`** tool to pull in the shared skills below.

| Agent | Purpose | Files? | MCP |
|-------|---------|--------|-----|
| [`orchestrator`](.claude/agents/orchestrator.md) | Coordination contract (the top-level session embodies it) | — | none |
| [`engineer`](.claude/agents/engineer.md) | Implements features/fixes (deep modules + clean code + GoF) | yes | none |
| [`test-engineer`](.claude/agents/test-engineer.md) | Writes tests first (TDD), keeps the suite green | yes | none |
| [`reviewer`](.claude/agents/reviewer.md) | Reviews the diff against standards + spec | no (read-only) | none |
| [`doc-writer`](.claude/agents/doc-writer.md) | Authors Wiki content and Swagger specs | yes (drafts) | none |
| [`linear-ticket-agent`](.claude/agents/linear-ticket-agent.md) | Linear issue triage + gated updates | no | narrow `{{MCP_SERVER}}` (reads + `save_comment`/`save_issue`) |

A non-specialist that discovers it needs external data must **ask the
Orchestrator**, which routes it to the appropriate specialist (e.g.
`linear-ticket-agent` for Linear) — it never reaches for an MCP tool itself.

---

## Standard workflow

1. **Orchestrator** ensures a **Linear vertical-slice ticket** exists — delegating
   to `linear-ticket-agent` to mint one (approval-gated) if needed. No PR is opened
   without it. It also gathers any needed context via the same specialist — it
   never calls `mcp__{{MCP_SERVER}}__*` directly.
2. **Orchestrator** creates a worktree + feature branch
   (`worktree-pr-workflow` skill) and notes its absolute path.
3. **Orchestrator → `test-engineer`**: write the failing tests for the change
   (TDD red), operating inside the worktree.
4. **Orchestrator → `engineer`**: implement until the tests pass (green), then
   refactor, honoring the engineering standards.
5. **Orchestrator → `doc-writer`**: draft/update Wiki content and any Swagger
   docs — **including the [[Workflow]] page whenever the workflow itself changed**.
6. **Orchestrator → `reviewer`**: review the diff; loop back to step 4 if needed.
7. **Orchestrator** runs the full test suite, commits within the worktree, pushes
   the branch, publishes/updates the Wiki, and **opens a PR — linking its Linear
   ticket** — as the report back.
8. A **human** reviews, approves, and merges. The Orchestrator never merges.

---

## Skills

Project skills (in `.claude/skills/`, shared with the whole team):

- [`worktree-pr-workflow`](.claude/skills/worktree-pr-workflow/SKILL.md) — the mandatory worktree → work → PR loop.
- [`swagger-docs`](.claude/skills/swagger-docs/SKILL.md) — produce/maintain OpenAPI (Swagger) docs for REST endpoints.
- [`wiki-docs`](.claude/skills/wiki-docs/SKILL.md) — author (sub-agent) and publish (Orchestrator) documentation in the Wiki.
- [`linear-ticket-workflow`](.claude/skills/linear-ticket-workflow/SKILL.md) — inspect / summarize / update a Linear issue via the `linear-ticket-agent` (Tool Gateway).
- [`wave-plan`](.claude/skills/wave-plan/SKILL.md) — turn a Linear Planning Document (`.LPD` in `./docs`) into dependency-layered waves → `docs/wave.yml` + a Linear parent issue with one or many sub-issues (one per wave ticket).

Helpful plugin skills when installed: `codebase-design` (deep modules),
`domain-modeling`, `tdd`, `review`.

---

## Tool Gateway — rules & limits

MCP is governed by a **Tool Gateway** (a logical control layer, not an app).
The detailed policies live in `.claude/rules/` and are **imported** below with
Claude Code's `@` syntax, so they load as active governance (not just links):

@.claude/rules/orchestration.md
@.claude/rules/tool-gateway.md
@.claude/rules/mcp-security.md
@.claude/rules/approvals.md
@.claude/rules/audit-reporting.md
@.claude/rules/ticketing.md

**Enforcement:** each specialist's `tools:` allow-list (hard, deny-by-default) +
`.claude/settings.json` permissions (`deny` → `ask` → `allow`: reads allowed, writes
`ask` for human approval, `delete_*` denied) + the `.claude/hooks/` audit hook.
MCP credentials live in the Claude Code connection layer — never in the repo or in
prompts.

**Honest limits vs. the ideal gateway:** no stable/internal tool-name aliasing
(upstream names exposed verbatim); no tenant isolation; no durable execution ids
(audit has timestamp + session id only); no rate limiting; approval is a live
prompt, not a stored expiring token; the session default is "prompt," and true
deny-by-default holds only *inside* a specialist (its `tools:` list). The
Orchestrator-has-no-MCP boundary is **procedural** today (permissions are
session-wide and cannot single out the root session); the structural hardening is to
move `{{MCP_SERVER}}` into `linear-ticket-agent`'s `mcpServers:` frontmatter so
only it connects. Prefer an org-owned Linear identity over a personal one
(`{{MCP_SERVER}}` may be personal today).

---

## Build & test

```bash
{{BUILD_CMD}}            # install dependencies
{{TEST_CMD}}             # run the test suite (no credentials needed)
{{CONNECTIVITY_CMD}}     # verify external connectivity (needs credentials)
```

Enable the guard hooks once per clone (blocks commits/pushes to `main`):

```bash
git config core.hooksPath .githooks
```

---

## Repo map

```
{{REPO_MAP}}
.claude/agents/    orchestrator + specialists (engineer … linear-ticket-agent)
.claude/skills/    the project skills above
.claude/rules/     Tool Gateway policy (tool-gateway, mcp-security, approvals, …)
.claude/hooks/     MCP audit hook + recommended-hooks README
.claude/settings.json  MCP permissions (allow reads / ask writes / deny delete)
.githooks/         guard hooks (block commits/pushes to main)
```
