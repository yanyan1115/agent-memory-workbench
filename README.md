# Agent Memory Workbench

Auditable, file-first memory infrastructure for AI agents.

An agent should not need to search its own archive before it can say, "I
remember." The small set of facts and rules that matter at startup should
already be present. Search should be reserved for details.

Agent Memory Workbench is not another attempt to make retrieval the center of
memory. It is a layered, auditable architecture for maintaining memory over
time: durable Markdown records, a compact hot index, reviewable admission,
hierarchical navigation, optional hybrid retrieval, integrity checks, and safe
cross-host operation.

## Why

An agent's active context, session checkpoint, transcript, and long-term memory
solve different problems. This project handles long-term memory. It does not
replace the model's context manager or claim that a generated summary is an
authoritative transcript.

Core principles:

- Markdown is authoritative; indexes and vectors are rebuildable.
- `MEMORY.md` is a small human-curated hot index, not the whole library.
- Candidates are reviewed before becoming formal memory.
- Private memory is excluded from remote embedding and search by default.
- Current instructions, permissions, and runtime state override old memory.
- Multiple writers share one lock domain; network failure degrades read-only.
- Automatic recall is optional, bounded, untrusted, and fail-open.

## How It Works

### Admit new memory deliberately

- New information enters an inbox before it becomes formal memory.
- A human or agent reviews and promotes useful candidates; low-value material
  can be discarded instead of silently becoming permanent context.

### Know the important things at startup

- `MEMORY.md` is a lightweight hot index suitable for startup loading. Each
  pointer keeps only a useful hook, with a hard 200-character line budget.
- The hot index, generated area indexes, domain hubs, and optional skills form
  a navigable tree. Validated wiki links can connect related memories directly.
- High-frequency rules whose omission would be costly can live in skills and
  use skill descriptions as low-noise recall triggers. Lower-frequency facts
  remain in Markdown and are opened only when needed.

### Retrieve details when needed

- `memsearch` combines lexical search with optional Gemini or OpenAI-compatible
  embeddings. Markdown remains authoritative and lexical search works without
  an API or vector cache.
- `memory-recall` is an optional message-gateway adapter with time, size, and
  fail-open bounds. The workbench remains fully usable without it.
- Vector overlap review surfaces memories that may duplicate or contradict one
  another. Similarity is evidence for review, never automatic permission to
  merge or delete.

### Keep the library healthy

- `memoryctl`: initialize, validate, index, stage, promote, and archive memories.
- Hard 200-character hot-index budget, dead-link checks, wiki links, and heading validation.
- Reasoned updates and a hash-only lifecycle audit trail.
- `memory-mirror`: validated immutable read-only fallback releases.
- NFSv4-over-SSH deployment guidance for one authority across multiple hosts.
- Offline `unittest` suite with privacy and stale-cache regressions.

## Install

This release supports Python 3.10+ on POSIX systems.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Quick Start

```bash
memoryctl init ./memory

printf '%s\n' 'Use the release checklist before publishing.' > /tmp/body.md
memoryctl candidate --root ./memory \
  --name release-checklist \
  --description 'Release validation conventions.' \
  --type reference \
  --source manual \
  --source-agent example-agent \
  --body-file /tmp/body.md

memoryctl promote --root ./memory \
  inbox/public/release-checklist.md --to active \
  --reason 'Reviewed and approved'
memoryctl doctor --root ./memory
memsearch search --root ./memory 'release validation'
```

Lexical search requires no API or semantic cache. For Gemini semantic search:

```bash
export EMBEDDING_API_KEY='set this outside shell history'
memsearch index --root ./memory --provider gemini
memsearch search --root ./memory --provider gemini 'release validation'
```

The semantic cache defaults to
`$XDG_STATE_HOME/agent-memory-workbench` or
`~/.local/state/agent-memory-workbench`, outside the memory repository. It does
not store plaintext memory bodies.

Private memory requires explicit opt-in on both indexing and querying:

```bash
memsearch index --root ./memory --provider gemini --include-private
memsearch search --root ./memory --provider gemini --include-private 'query'
```

Before enabling this, confirm that sending private text to the selected remote
embedding provider is acceptable for your deployment.

## Memory Layout

```text
memory/
├── MEMORY.md                 # manually curated hot pointers
├── active/                   # formal current public memory
├── archive/                  # formal historical public memory
├── private/                  # formal private memory
├── inbox/
│   ├── public/               # unreviewed public candidates
│   └── private/              # unreviewed private candidates
└── .memory-workbench.lock    # shared lock domain
```

`active/INDEX.md`, `archive/INDEX.md`, and `private/INDEX.md` are generated.
Never edit them manually.

`memoryctl doctor` checks schema, duplicate identities, filename/name agreement,
stale generated indexes, dead hot-index links, the 200-character hot-index line
budget, wiki-link targets, and wiki heading anchors.

Use explicit reasons for edits and review the content-free audit trail:

```bash
memoryctl update --root ./memory release-checklist \
  --body-file ./revised.md \
  --reason 'Corrected the release evidence'
memoryctl audit --root ./memory
```

After semantic indexing, inspect high-similarity cross-file chunks:

```bash
memsearch overlap --root ./memory --threshold 0.90
```

## Documentation

- [Architecture](docs/architecture.md)
- [Data model and lifecycle](docs/data-model.md)
- [Privacy and threat model](docs/privacy-and-security.md)
- [Optional automatic recall](docs/automatic-recall.md)
- [Cross-host NFSv4 over SSH](docs/deployment/nfs-over-ssh.md)
- [Agent memory skill template](docs/memory-skill-template.md)
- [Security policy](SECURITY.md)
- [Contributors](CONTRIBUTORS.md)

## Origins

This architecture grew out of long-running real-world iteration by Cora,
Claude, and South. Cora set and continuously corrected the architectural
direction, then pushed the private practice toward an open-source release.
Claude helped evolve the memory library, Memory skill, hot-index budget,
low-noise recall, inbox, hierarchical hubs, doctor, and overlap workflows.
South reconciled the implementations and completed the public architecture
audit, privacy review, code, tests, documentation, and release. See
[CONTRIBUTORS.md](CONTRIBUTORS.md) for the full attribution.

Using skills for selectively loaded long-term rules was inspired by a
second-hand description of Codex Desktop's native memory behavior; no Codex
source code was consulted. Treating the skill description itself as the recall
trigger is this project's own design.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Project Status

Version `0.2.0` is a conservative reference implementation. It intentionally
does not automate memory extraction from complete transcripts or perform
automatic conflict resolution. Those are judgment-heavy operations and should
remain reviewable.

## License

MIT
