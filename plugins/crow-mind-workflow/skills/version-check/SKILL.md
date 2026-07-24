---
name: version-check
description: Report whether the installed crow-mind-workflow plugin is up to date with the published marketplace, and surface update instructions when it is behind. Use when the user asks "am I on the latest crow-mind?", "check for plugin updates", "is crow-mind-workflow up to date?", or before running init-repo / sync-baseline.
user-invocable: true
---

# version-check

Tell the user whether their installed **crow-mind-workflow** plugin is current,
and — if it is behind the published marketplace — surface the exact update
commands. This skill reads a cache written by the plugin's `SessionStart` hook
(`scripts/check-version.sh`), so the answer is normally instant and needs no
network call.

## How the mechanism fits together

- On session start, the plugin hook (`hooks/hooks.json` →
  `scripts/check-version.sh`) fetches the published marketplace manifest,
  compares its `crow-mind-workflow` version to the installed
  `.claude-plugin/plugin.json` version, and writes the verdict to
  **`${CLAUDE_PLUGIN_DATA}/version-status.json`**.
- That cache is the single source of truth every skill/tool use reads to
  re-surface the "update available" reminder **without re-fetching**.
- The cache shape (stable contract) is:

  ```json
  {
    "status": "up-to-date | behind | unknown",
    "installed": "0.1.0",
    "latest": "0.1.0",
    "checkedAt": "<ISO-8601 UTC>",
    "updateInstructions": "<multi-line; empty unless behind>"
  }
  ```

## What to do

1. Read `${CLAUDE_PLUGIN_DATA}/version-status.json`.
2. Branch on `status`:
   - **`behind`** — show the `updateInstructions` string verbatim to the user
     (it already contains the `/plugin marketplace update` and `/plugin update`
     commands). Mention the `installed` → `latest` versions.
   - **`up-to-date`** — say so briefly, e.g. "crow-mind-workflow is up to date
     (`<installed>`)." Do not nag.
   - **`unknown` or the file is missing** — the last check could not reach the
     marketplace (or has not run yet). Refresh by running
     `${CLAUDE_PLUGIN_ROOT}/scripts/check-version.sh`, then re-read the cache and
     report the refreshed `status`. If it is still `unknown`, tell the user the
     update check could not reach the network and they can retry later.

Never fabricate a version. Only report what the cache (or a fresh run of the
script) actually contains.

## PREFLIGHT snippet (embed at the start of init-repo and sync-baseline)

The `init-repo` and `sync-baseline` skills begin with the block below so that
**every** governance action re-surfaces a pending update before proceeding. Copy
it verbatim into the top of those skills:

<!-- BEGIN crow-mind-workflow version PREFLIGHT -->
> **Preflight — plugin version check.**
> Read `${CLAUDE_PLUGIN_DATA}/version-status.json`.
> - If `status == "behind"`, surface its `updateInstructions` to the user
>   **before** doing anything else, and let them decide whether to update first.
> - If the file is missing or `status == "unknown"`, run
>   `${CLAUDE_PLUGIN_ROOT}/scripts/check-version.sh` once to refresh it, then
>   re-read and apply the rule above.
> - If `status == "up-to-date"`, proceed silently.
>
> This is a non-blocking reminder: a stale or unreachable check never prevents
> the skill from running.
<!-- END crow-mind-workflow version PREFLIGHT -->
