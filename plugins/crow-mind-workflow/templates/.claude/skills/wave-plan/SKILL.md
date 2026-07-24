---
name: wave-plan
description: Turn a Linear Planning Document (.LPD in ./docs) into dependency-layered execution waves — writes docs/wave.yml and creates a Linear parent issue with one or many sub-issues (one per wave ticket). Use when the user says "wave plan", "plan waves", "wave-plan", or wants to break an LPD into parallelizable ticket waves.
---

# wave-plan

Turn a **Linear Planning Document (LPD)** into an execution **wave plan**:
vertical-slice tickets grouped into waves that can run in parallel, materialized as
`docs/wave.yml` and as a Linear **parent issue** with **one or many sub-issues** —
one per wave ticket (a single wave can contribute several).

This skill grants **no tools**. All Linear writes go through the
[`linear-ticket-agent`](../../agents/linear-ticket-agent.md) — Orchestrator-delegated
and approval-gated — per the [Tool Gateway](../../rules/tool-gateway.md) and
[ticketing](../../rules/ticketing.md) rules.

## Input

- A **`.LPD`** (Linear Planning Document) found in **`./docs`** (e.g.
  `docs/<name>.LPD` or `docs/LPD.md`). It describes the work for a
  project/initiative.

## Output

1. **`docs/wave.yml`** — the computed wave plan.
2. **Linear issues** — a parent issue plus **one sub-issue per wave ticket** (so one
   or many sub-issues in total — a wave can have several), created via
   `linear-ticket-agent`.

## Tags

- **TEAM** — the team key; **defaults to `{{LINEAR_TEAM}}`**.
- **PROJECT** — the project tag (a short slug), written as `P-<project tag>` in
  titles. The Orchestrator supplies the current default project (see the
  default-project convention in [ticketing](../../rules/ticketing.md)); if unknown,
  ask.

## Procedure

### 1. Read the LPD
Locate and read the `.LPD` in `./docs`. Extract the goal, the discrete pieces of
work, and any stated sequencing/dependencies.

### 2. Break into vertical slices
Decompose the plan into **vertical slices** — each a complete, shippable slice of
behavior (not a horizontal layer), per the ticketing rule. Each slice becomes one
ticket with: a short **name**, a **description**, and its **dependencies** (which
other slices must finish first).

### 3. Layer into waves (1-based)
Assign each slice to a wave by dependency depth:
- **Wave 1** = every slice with **no** dependencies.
- **Wave k** = every slice whose dependencies are *all* satisfied by waves `< k`
  (i.e. `wave = 1 + max(wave of its blockers)`).
- A slice **blocked by** another always lands in a **later** wave than its blocker.
- Waves start at **1** (never 0). A wave holds **one or more** tickets. All tickets
  within a wave are mutually independent → safe to run in **parallel**.

### 4. Write `docs/wave.yml`
Write the plan to `docs/wave.yml` using the schema below.

### 5. Create the Linear structure (delegated to `linear-ticket-agent`)
The Orchestrator delegates to `linear-ticket-agent`; every create is a
**approval-gated** write:
- Create the **parent** issue — title `[<TEAM>][P-<PROJECT>] <plan name>` — on team
  TEAM, under the current default project. This one parent hosts **all** wave tickets
  as sub-issues (one or many).
- Create each wave ticket as a **sub-issue** of the parent (`save_issue` with
  `parentId` = the parent's id) — title `[<TEAM>][P-<PROJECT>][Wave N] <ticket name>`
  — on team TEAM, under the project. Encode dependencies with `blockedBy` (each ticket
  lists the earlier-wave tickets that block it).
- Record the returned issue identifiers back into `docs/wave.yml`.

> Note on the parent "label": the parent's **title** uses the `[<TEAM>][P-<PROJECT>]`
> format above. If an actual Linear **label** is also wanted on the parent, apply it
> via `save_issue` `labels` — confirm with the requester.

## `docs/wave.yml` schema

```yaml
plan: <plan name>              # from the LPD
team: {{LINEAR_TEAM}}          # TEAM (defaults to {{LINEAR_TEAM}})
project: <project tag>         # PROJECT (rendered as P-<project tag> in titles)
parent:
  title: "[{{LINEAR_TEAM}}][P-<project>] <plan name>"
  id: <linear id, once created>
waves:
  - wave: 1
    tickets:
      - name: <ticket name>
        title: "[{{LINEAR_TEAM}}][P-<project>][Wave 1] <ticket name>"
        description: <what this slice delivers>
        dependsOn: []           # names of blocker tickets (empty in wave 1)
        id: <linear id, once created>
  - wave: 2
    tickets:
      - name: <ticket name>
        title: "[{{LINEAR_TEAM}}][P-<project>][Wave 2] <ticket name>"
        description: <...>
        dependsOn: [<wave-1 ticket name>]
        id: <...>
```

## Rules & boundaries

- Titles use the **exact** bracket format above; **TEAM defaults to `{{LINEAR_TEAM}}`**.
- Every ticket is a vertical slice, is a **sub-issue of the parent**, and rolls up
  under the current default project ([ticketing](../../rules/ticketing.md)).
- Only `linear-ticket-agent` touches Linear; every issue create is approval-gated.
  This skill creates no issues itself and holds no tools.
- Re-running the skill updates `docs/wave.yml` and should reconcile (not duplicate)
  existing issues where possible.
