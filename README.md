# Agent Memory Workbench

Auditable, file-first memory infrastructure for AI agents.

Agent Memory Workbench keeps durable memory in ordinary Markdown. It adds a
review inbox, deterministic indexes, hybrid lexical/vector search, bounded
optional recall, cross-process locking, and validated read-only mirrors without
turning an opaque database into the source of truth.

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

## Features

- `memoryctl`: initialize, validate, index, stage, promote, and archive memories.
- `memsearch`: lexical search plus optional Gemini or OpenAI-compatible embeddings.
- Hard 200-character hot-index budget, dead-link checks, wiki links, and heading validation.
- Hierarchical navigation through a hot index, generated area indexes, domain hubs, and skills.
- Reasoned updates and a hash-only lifecycle audit trail.
- Vector overlap detection for duplicate or conflicting memories.
- `memory-recall`: safe adapter for message gateways.
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
