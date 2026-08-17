# Agent Memory Skill Template

Use this as a starting point for an agent skill. Adapt paths and tools without
putting private memory bodies in the skill itself.

```markdown
---
name: memory
description: Use before creating, editing, deleting, promoting, archiving, indexing, or validating the shared memory library. Also use when resuming memory work after context compaction. Do not load for ordinary chat or read-only recollection.
---

# Shared Memory Operations

- Markdown is authoritative. Generated indexes, vectors, and exports are derived.
- Keep the hot `MEMORY.md` index small; detailed evidence stays in one memory file per durable subject.
- Use inbox candidates for unreviewed observations. A candidate is not formal memory until promoted.
- Record useful provenance, but never credentials, chat/user/session identifiers, or complete transcripts solely for provenance.
- Preserve superseded history and state the current policy clearly. Every update or archive needs an explicit reason; never alter a record when the complete original cannot be read.
- Before mutation, read the complete target and related records.
- Use lock-aware lifecycle commands. Never bypass the shared lock on a multi-writer deployment.
- Regenerate deterministic indexes, update semantic state on the elected index host, and run doctor once per batch.
- Private memory is excluded from remote embedding by default.
- High-frequency, long-lived procedures may become narrowly triggered skills. Keep the trigger in always-visible instructions.
- Keep each hot-index pointer within the configured budget. Domain hubs must cover their whole topic and group pointers by purpose.
- Use overlap results only as prompts for review; high similarity does not automatically mean duplication.
```

Always-loaded agent instructions should separately retain one short trigger:

> When a durable preference, boundary, project conclusion, or operational lesson appears, decide whether it should become a memory; load the memory skill before writing.

This avoids burying the only reminder inside the skill it is meant to trigger.
