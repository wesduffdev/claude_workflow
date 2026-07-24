# {{PROJECT_NAME}}

{{PROJECT_DESC}}

## Quick start

```bash
{{BUILD_CMD}}            # install dependencies
{{CONNECTIVITY_CMD}}     # verify the setup / external connectivity
```

## Documentation

Full documentation lives in the **[Wiki]({{WIKI_URL}})** — setup, architecture,
usage, and CI.

## Contributing

Read **[`CLAUDE.md`](CLAUDE.md)** first. In short: **never commit to `main`** —
all work happens in a `git worktree` on a feature branch and is delivered as a
Pull Request for human approval. Enable the guard hooks once with
`git config core.hooksPath .githooks`.

```bash
{{TEST_CMD}}   # run the tests (no credentials needed)
```
