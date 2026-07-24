---
name: swagger-docs
description: Produce and maintain Swagger / OpenAPI documentation for any REST API in this repo. Use whenever a REST endpoint is added or changed. Keeps the machine-readable spec in sync with the code and publishes a human-readable API reference to the Wiki.
---

# Swagger / OpenAPI docs for REST APIs

Repo rule: **every REST endpoint ships with Swagger (OpenAPI) documentation.**
This skill is how you satisfy it. *(This applies the moment a REST API is
introduced.)*

## Principles

- The spec is **derived from the code**, never hand-drifted. Prefer frameworks
  that generate OpenAPI from typed handlers/models so the spec cannot rot.
- Every endpoint documents: method + path, summary/description, parameters,
  request body schema, each response status with its schema, and auth.
- Model request/response bodies as **named, reusable schemas** (typed models or
  `components/schemas`) — not inline blobs. This mirrors the deep-module ethos:
  one clear contract, reused.
- Serve interactive docs and the raw spec, and expose the spec in CI so drift is
  caught.

## Framework guidance

**Generate, don't hand-write.** Pick a framework that emits OpenAPI from typed
handlers/models (e.g. FastAPI for Python, or an equivalent for your stack):
- Define request/response bodies as typed models/schemas.
- Annotate handlers with their response model, status codes, and a
  `summary`/`description` (docstrings often become descriptions).
- Serve interactive docs (Swagger UI / ReDoc) and the raw spec (e.g.
  `/openapi.json`).

If the framework has no built-in generator, add a spec-generation library
(schema + serializer) rather than maintaining hand-written YAML.

## Keeping it honest

- Add a test/CI check that the served spec matches the committed spec (or is
  regeneratable), so a code change that forgets the docs fails the build.
- Version the API (e.g. `/v1`) and note breaking changes.

## Publishing (Orchestrator only)

The **doc-writer** sub-agent produces the spec file and a human-readable API
reference page. The **Orchestrator** publishes that reference to the
[Wiki]({{WIKI_URL}}) via the `wiki-docs` skill.
The machine-readable spec (e.g. `openapi.json`/`openapi.yaml`) may live in the
repo next to the service, since it is a build artifact of the code, not prose.
