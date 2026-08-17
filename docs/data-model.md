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
  inbox/public/example-note.md --to active \
  --reason 'Reviewed and approved'
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

Each hot-index bullet has a hard 200-character maximum. It should contain only
a recognition hook and any safety boundary that must remain immediately
visible. `doctor` rejects dead hot-index links and over-budget lines.

## Tree Navigation And Links

The navigation tree has several layers:

```text
MEMORY.md hot index
    -> generated active/archive/private indexes
    -> optional domain hub
    -> individual memory
    -> related memory through [[wiki-links]]
```

Generated area indexes guarantee complete lifecycle coverage. A domain hub is a
normal memory that groups a coherent topic when that topic has a reliable
trigger. Keep broad safety rules in the hot index instead of hiding them behind
a hub.

Memory bodies may link by canonical name and optional heading:

```text
Related: [[release-checklist]]
Related: [[release-checklist#Rollback]]
```

`doctor` validates both the target and heading anchor.

## Archival

Archival preserves history instead of deleting it:

```bash
memoryctl archive --root ./memory example-note \
  --reason 'Superseded by the current deployment record.'
```

When a newer decision overrides an older one, preserve the old evidence and
state the current policy near the top. Do not silently rewrite history.

Use `memoryctl update --reason ...` for reasoned body changes. Lifecycle
operations append timestamps, paths, reasons, and before/after body hashes to
`.memory-workbench-audit.jsonl`; the audit contains no memory body. Manual
editor changes cannot be intercepted, so use Git or another versioned storage
layer when complete edit history is required.

Archived memories remain searchable. Existing historical Markdown can be
normalized to schema v1 and placed under `archive/`; there is no claim that
absence from the archive proves an event never happened.

## Semantic Cache

The semantic cache stores vectors and minimal identifiers, not plaintext body
content. Each vector is bound to the SHA-256 of the current chunk. Changed or
deleted text cannot reuse a stale vector. A failed index build does not replace
the previous complete generation.

Lexical search reads current Markdown directly and works without a provider.

`memsearch overlap` compares current compatible vectors across files to surface
near-duplicate or conflicting memories. A high score is a review signal, not
permission to delete: a policy record and an evidence record may intentionally
describe the same event.
