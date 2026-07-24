<!--
This PR is the "report back" for the change. A human reviews and merges it —
never self-merge. See CLAUDE.md for the rules.
-->

## Linear ticket

<!-- Required — no PR without a Linear vertical-slice ticket (minted in {{MCP_SERVER}}). -->
- Delivers:

## Summary

<!-- What does this change do, and why? One short paragraph. -->

## Changes

<!-- Bullet the notable changes (files / behavior). -->
-

## How this was built

<!-- Orchestrator + which sub-agents (engineer / test-engineer / reviewer /
     doc-writer). Note any external data the Orchestrator fetched via MCP. -->

## Testing

<!-- How you verified it. Paste `{{TEST_CMD}}` results. -->
```
{{TEST_CMD}}
```

## Documentation

<!-- Links to the Wiki pages added/updated. Prose docs go in the Wiki, not the repo. -->
- Wiki:

## Checklist

- [ ] Linked to a Linear vertical-slice ticket (minted in `{{MCP_SERVER}}`)
- [ ] Work was done in a `git worktree` on a feature branch — **not** `main`
- [ ] If the workflow changed, the **Workflow** wiki page was updated
- [ ] `{{TEST_CMD}}` passes
- [ ] Follows the standards in `CLAUDE.md` (deep modules, clean code, GoF only where it simplifies)
- [ ] REST changes include Swagger/OpenAPI docs (or N/A)
- [ ] Prose documentation updated in the **Wiki** (or N/A)
- [ ] Root `README.md` kept simple (or N/A)
- [ ] Requesting **human** review & merge (no self-merge)
