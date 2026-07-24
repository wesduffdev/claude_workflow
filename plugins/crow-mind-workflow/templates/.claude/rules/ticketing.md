# Rule: Ticketing (Linear vertical slices)

Every change traces to a Linear ticket. **No PR is opened without one.**

## The rule

- Before a PR is opened, a **vertical-slice ticket** must exist in Linear
  (`{{MCP_SERVER}}`) describing the slice of work the PR delivers.
- The ticket is minted via the
  [`linear-ticket-agent`](../agents/linear-ticket-agent.md) using `save_issue`
  (create) — a **write**, so it is **approval-gated** ([approvals](approvals.md)).
  The Orchestrator delegates; it never calls `{{MCP_SERVER}}` itself.
- The PR **links its ticket** (id in the PR body / template).
- **Every ticket is associated with a project.** The Orchestrator supplies the
  current default project when delegating; if none is provided, `linear-ticket-agent`
  lists the projects and **asks** which to use before creating (never project-less).
- Prefer **vertical slices**: a ticket describes a complete, shippable slice of
  behavior, not a horizontal layer.

## Orchestrator responsibility

At the start of a task the Orchestrator confirms a suitable ticket exists, or mints
one via the specialist (approval-gated), **before** any PR. If work is already
underway without a ticket, stop and mint one before opening the PR.

## Notes

- Ticket creation is a Linear write: expect a human-approval prompt.
- Do **not** fabricate a ticket id — the id must come from a real `{{MCP_SERVER}}`
  ticket returned by the create call.
- Reads used to find or verify a ticket (`list_issues`, `get_issue`) are automatic;
  the create/update (`save_issue`) is approval-gated.
