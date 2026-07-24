# Rule: Approvals

Protected writes require **explicit human approval** before they run. In this repo
the approval is enforced by `.claude/settings.json` (`ask` rules prompt at call
time) and by the specialist agents, which must surface the request rather than act
silently.

## Require human approval before

- creating or modifying business records (e.g. Linear comments, issue fields)
- changing issue status
- assigning issues
- closing issues
- merging code
- publishing content (e.g. Wiki)
- uploading or deleting files
- changing permissions
- sending external communications
- running any destructive operation

## Approval is specific and non-permanent

An approval applies only to:

- the **action**,
- the **target**,
- the **proposed change**, and
- the **current execution**.

Approval for one action is **never** permanent approval for future actions. Do not
treat a prior "yes" as standing authorization, and do not use a broadened
"don't ask again" grant to bypass this rule.

## How to request approval

When approval is required, **stop** and present clearly:

```
Approval requested:
  System:          <e.g. Linear>
  Tool:            <e.g. save_comment>
  Target:          <e.g. issue ENG-101>
  Proposed change: <exact content / field change>
  Reason:          <why this is needed>
  Risk:            <what could go wrong>
```

Then wait for the human decision. If denied, do not perform the action; report the
denial in the result summary (see [audit-reporting](audit-reporting.md)).
