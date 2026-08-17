# Data Model And Lifecycle

## Memory Schema

```yaml
---
schema_version: 1
name: release-checklist
description: Release validation conventions.
type: reference
status: active
visibility: public
source: manual
source_agent: example-agent
created: 2026-01-01
tags:
  - release
aliases: []
---

Markdown body with evidence, decisions, and useful context.
```

Required top-level fields are `schema_version`, `name`, `description`, and
`type`. Names are lowercase hyphenated slugs. The body must not be empty.

Useful provenance includes source type and date, source agent, related project,
and verifiable file, commit, or issue references. Do not store credentials,
chat/user/session identifiers, or full transcripts merely for provenance.

## Candidate Inbox

Candidates are durable drafts, not formal memory. They are excluded from
generated indexes and search.

```bash
memoryctl candidate --root ./memory \
  --name example-note \
  --description 'A reviewable candidate.' \
  --type note \
  --body-file ./draft.md

memoryctl promote --root ./memory \
  inbox/public/example-note.md --to active
```

Use `--private` when creating a private candidate and `--to private` when
promoting it.

## Indexes

`MEMORY.md` is manually curated and remains small. The three lifecycle indexes
are deterministic:

```bash
memoryctl index --root ./memory write
memoryctl index --root ./memory check
memoryctl doctor --root ./memory
```

## Archival

Archival preserves history instead of deleting it:

```bash
memoryctl archive --root ./memory example-note \
  --reason 'Superseded by the current deployment record.'
```

When a newer decision overrides an older one, preserve the old evidence and
state the current policy near the top. Do not silently rewrite history.

## Semantic Cache

The semantic cache stores vectors and minimal identifiers, not plaintext body
content. Each vector is bound to the SHA-256 of the current chunk. Changed or
deleted text cannot reuse a stale vector. A failed index build does not replace
the previous complete generation.

Lexical search reads current Markdown directly and works without a provider.
