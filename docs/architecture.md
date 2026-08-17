# Architecture

## Four Different Layers

Do not collapse these into one summary file:

1. **Active context**: what the model sees now.
2. **Session checkpoint**: a bounded state used to resume an interrupted task.
3. **Durable transcript or ledger**: append-only evidence for audit and replay.
4. **Long-term memory**: curated knowledge useful across tasks.

Agent Memory Workbench implements layer 4. A gateway may inject selected
long-term clues into layer 1, but the two remain separate.

## Authority Model

```text
Markdown files (authority)
    ├── generated INDEX.md files (disposable)
    ├── semantic vectors (disposable, outside repository)
    ├── optional dashboard/export views (disposable)
    └── immutable fallback mirrors (read-only copies)
```

An embedding result, search excerpt, or recall block is never allowed to edit
Markdown automatically. Search points the agent back to a source file, which
must be read before making a high-impact decision.

## Write Lifecycle

```text
observation
    -> inbox candidate
    -> human/agent review
    -> active or private formal memory
    -> archive when no longer current
```

Low-value observations may produce no candidate. A memory library is a curated
sample, not a complete log.

All lifecycle commands take an advisory `fcntl.flock`. Writes use a temporary
file in the destination directory, `fsync`, `os.replace`, and directory
`fsync`. Non-cooperating editors do not honor the advisory lock; on shared
deployments, use a lock-aware command or an exclusive maintenance window for
manual edits.

## Read Lifecycle

```text
small MEMORY.md hot index
    -> generated domain index
    -> lexical or hybrid search
    -> read 1-2 authoritative files
```

Skill descriptions can serve as a low-noise recall index for high-frequency,
long-lived procedures. Keep the trigger visible in always-loaded instructions;
do not bury the only reminder inside the skill it must trigger.

Navigation is deliberately tree-shaped rather than one giant flat summary:
the hot index points to generated lifecycle indexes or domain hubs; hubs point
to complete topic-specific memories and skills; memories may link to one
another with validated wiki links. A main skill can provide the entry trigger
and route to smaller subskills without loading every procedure at startup.

## Multi-Host Model

One host owns the physical backing filesystem. Every writer, including that
host, accesses the library through the same canonical NFSv4 mount so all locks
share one server-side lock domain. Remote clients reach loopback-only NFS
through an SSH tunnel.

Only one configured host builds semantic indexes. Other hosts may search the
completed cache. During authority loss, clients use a validated immutable
mirror mounted read-only. They never create an independent writable copy.

Git may synchronize public code, rules, or skills, but not the durable memory
tree. Git clones and an NFS authority have different conflict models and must
not be confused.
