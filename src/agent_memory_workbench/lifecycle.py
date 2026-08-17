from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .core import (
    AREAS,
    GENERATED_MARKER,
    MemoryError,
    SLUG_RE,
    atomic_write,
    load_memories,
    memory_lock,
    parse_memory,
    render_memory,
    resolve_root,
    safe_path,
    validate_memory,
)


def render_index(area: str, memories) -> str:
    title = area.title() + " Memory Index"
    lines = [f"# {title}", "", GENERATED_MARKER, ""]
    grouped: dict[str, list] = {}
    for memory in memories:
        grouped.setdefault(str(memory.data.get("type", "other")), []).append(memory)
    for kind in sorted(grouped):
        lines.extend([f"## {kind.title()}", ""])
        for memory in sorted(grouped[kind], key=lambda item: item.data["name"]):
            rel = Path(memory.relative).relative_to(area).as_posix()
            lines.append(f"- [{memory.data['name']}]({rel}) - {memory.data['description']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def expected_indexes(root: Path) -> dict[Path, str]:
    memories = load_memories(root)
    result = {}
    for area in AREAS:
        selected = [m for m in memories if m.relative.startswith(area + "/")]
        result[root / area / "INDEX.md"] = render_index(area, selected)
    return result


def cmd_init(args) -> int:
    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for rel in (*AREAS, "inbox/public", "inbox/private"):
        (root / rel).mkdir(parents=True, exist_ok=True)
    memory_md = root / "MEMORY.md"
    if not memory_md.exists():
        atomic_write(memory_md, "# Memory\n\nCurated hot pointers only.\n", default_mode=0o644)
    for path, text in expected_indexes(root).items():
        if not path.exists():
            atomic_write(path, text, default_mode=0o644)
    return 0


def collect_issues(root: Path) -> list[str]:
    issues: list[str] = []
    try:
        memories = load_memories(root, candidates=True)
    except MemoryError as exc:
        return [str(exc)]
    identities: dict[str, str] = {}
    for memory in memories:
        for issue in validate_memory(memory):
            issues.append(f"{memory.relative}: {issue}")
        names = [memory.data.get("name"), *memory.data.get("aliases", [])]
        for name in filter(lambda value: isinstance(value, str), names):
            if name in identities:
                issues.append(f"{memory.relative}: duplicate identity {name} (also {identities[name]})")
            else:
                identities[name] = memory.relative
    return issues


def cmd_doctor(args) -> int:
    root = resolve_root(args.root)
    with memory_lock(root, exclusive=False, timeout=args.lock_timeout):
        issues = collect_issues(root)
        for path, expected in expected_indexes(root).items():
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                issues.append(f"{path.relative_to(root)}: generated index is stale")
    for issue in issues:
        print(f"ERROR {issue}")
    print(f"doctor: {len(issues)} error(s)")
    return 1 if issues else 0


def cmd_index(args) -> int:
    root = resolve_root(args.root)
    with memory_lock(root, exclusive=args.mode == "write", timeout=args.lock_timeout):
        indexes = expected_indexes(root)
        if args.mode == "check":
            stale = [path for path, text in indexes.items() if not path.exists() or path.read_text(encoding="utf-8") != text]
            for path in stale:
                print(f"stale: {path.relative_to(root)}")
            return 1 if stale else 0
        for path, text in indexes.items():
            atomic_write(path, text, default_mode=0o644)
    return 0


def read_body(args) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8").strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise MemoryError("provide --body-file or pipe body text on stdin")


def cmd_candidate(args) -> int:
    root = resolve_root(args.root)
    if not SLUG_RE.fullmatch(args.name):
        raise MemoryError("name must be a lowercase hyphenated slug")
    body = read_body(args)
    if not body:
        raise MemoryError("body must not be empty")
    privacy = "private" if args.private else "public"
    target = root / "inbox" / privacy / f"{args.name}.md"
    data = {
        "schema_version": 1,
        "name": args.name,
        "description": args.description,
        "type": args.type,
        "status": "candidate",
        "visibility": privacy,
        "source": args.source,
        "source_agent": args.source_agent,
        "created": date.today().isoformat(),
        "tags": args.tag,
    }
    with memory_lock(root, exclusive=True, timeout=args.lock_timeout):
        if target.exists():
            raise MemoryError(f"candidate already exists: {target.relative_to(root)}")
        atomic_write(target, render_memory(data, body))
    print(target.relative_to(root))
    return 0


def cmd_promote(args) -> int:
    root = resolve_root(args.root)
    with memory_lock(root, exclusive=True, timeout=args.lock_timeout):
        source = safe_path(root, args.path, must_exist=True)
        memory = parse_memory(source, root)
        if not memory.relative.startswith("inbox/"):
            raise MemoryError("only inbox candidates can be promoted")
        target_area = "private" if args.to == "private" else "active"
        target = root / target_area / source.name
        if target.exists():
            raise MemoryError(f"destination exists: {target.relative_to(root)}")
        data = dict(memory.data)
        data["status"] = "active"
        data["visibility"] = "private" if target_area == "private" else "public"
        atomic_write(target, render_memory(data, memory.body))
        source.unlink()
        for path, text in expected_indexes(root).items():
            atomic_write(path, text, default_mode=0o644)
    print(target.relative_to(root))
    return 0


def cmd_archive(args) -> int:
    root = resolve_root(args.root)
    with memory_lock(root, exclusive=True, timeout=args.lock_timeout):
        matches = [m for m in load_memories(root) if m.data.get("name") == args.name]
        if len(matches) != 1:
            raise MemoryError(f"expected one active memory named {args.name}, found {len(matches)}")
        memory = matches[0]
        if not memory.relative.startswith("active/"):
            raise MemoryError("only active public memories can be archived")
        target = root / "archive" / memory.path.name
        if target.exists():
            raise MemoryError(f"destination exists: {target.relative_to(root)}")
        data = dict(memory.data)
        data["status"] = "archived"
        data["archive_reason"] = args.reason
        atomic_write(target, render_memory(data, memory.body))
        memory.path.unlink()
        for path, text in expected_indexes(root).items():
            atomic_write(path, text, default_mode=0o644)
    print(target.relative_to(root))
    return 0


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root")
    common.add_argument("--lock-timeout", type=float, default=10.0)
    root = argparse.ArgumentParser(description="Manage a file-first agent memory library")
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("root")
    init.set_defaults(func=cmd_init)
    doctor = sub.add_parser("doctor", parents=[common])
    doctor.set_defaults(func=cmd_doctor)
    index = sub.add_parser("index", parents=[common])
    index.add_argument("mode", choices=("write", "check"))
    index.set_defaults(func=cmd_index)
    candidate = sub.add_parser("candidate", parents=[common])
    candidate.add_argument("--name", required=True)
    candidate.add_argument("--description", required=True)
    candidate.add_argument("--type", required=True)
    candidate.add_argument("--source", default="manual")
    candidate.add_argument("--source-agent", default="unknown")
    candidate.add_argument("--tag", action="append", default=[])
    candidate.add_argument("--body-file")
    candidate.add_argument("--private", action="store_true")
    candidate.set_defaults(func=cmd_candidate)
    promote = sub.add_parser("promote", parents=[common])
    promote.add_argument("path")
    promote.add_argument("--to", choices=("active", "private"), required=True)
    promote.set_defaults(func=cmd_promote)
    archive = sub.add_parser("archive", parents=[common])
    archive.add_argument("name")
    archive.add_argument("--reason", required=True)
    archive.set_defaults(func=cmd_archive)
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (MemoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
