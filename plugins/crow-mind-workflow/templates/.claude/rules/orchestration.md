# Rule: Orchestration

The **top-level Claude session is the Orchestrator.** It coordinates work; it does
not do specialist work itself, and it does not hold business-system MCP access. See
also [tool-gateway](tool-gateway.md) and the agent contract in
[`.claude/agents/orchestrator.md`](../agents/orchestrator.md).

## The Orchestrator is responsible for

- Reading the requested workflow / user intent.
- Ensuring a Linear **vertical-slice ticket** exists (minted via
  `linear-ticket-agent`, approval-gated) **before any PR** — see [ticketing](ticketing.md).
- Selecting the appropriate specialist agent.
- Delegating the work with a clear **task package** (below).
- Tracking progress and results.
- Coordinating dependencies between specialists.
- Handling failures and retries.
- Requesting human approval when policy requires it.
- Reporting results (success, failure, blockers, next actions) with evidence.

## The Orchestrator must NOT

- Call unrestricted or business-system MCP tools (Linear, GitHub-via-MCP, etc.).
- Hold business-system credentials.
- Perform specialist work itself when a specialist exists.
- Bypass approval rules or silently perform writes.
- Open a PR without a linked Linear vertical-slice ticket.
- Mark work complete without evidence.

## Task package (what the Orchestrator hands each specialist)

Every delegation includes:

- **Objective** — what to accomplish.
- **Scope** — boundaries; what is explicitly out of scope.
- **Relevant identifiers** — e.g. the Linear issue id, the worktree path.
- **Permitted tools** — the narrow set the specialist may use for this task.
- **Prohibited actions** — anything it must not do.
- **Expected output** — the structured result shape (see [audit-reporting](audit-reporting.md)).
- **Completion criteria** — how "done" is judged.

## Delegation targets in this repo

- **`linear-ticket-agent`** — all Linear issue work (the only MCP-backed specialist today).
- **`engineer` / `test-engineer` / `reviewer` / `doc-writer`** — code, tests,
  review, and documentation authoring (MCP-free).
- GitHub/PRs/Wiki and worktree lifecycle stay with the Orchestrator via `gh`/git.
