from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .core import (
    AREAS,
    GENERATED_MARKER,
    HEADING_RE,
    HOT_INDEX_MAX_LINE,
    MD_LINK_RE,
    MemoryError,
    SLUG_RE,
    WIKI_RE,
    atomic_write,
    load_memories,
    markdown_target,
    memory_lock,
    parse_memory,
    render_memory,
    resolve_root,
    safe_path,
    validate_memory,
    heading_slug,
    wiki_parts,
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
        aliases = memory.data.get("aliases", [])
        names = [memory.data.get("name"), *(aliases if isinstance(aliases, list) else [])]
        for name in filter(lambda value: isinstance(value, str), names):
            if name in identities:
                issues.append(f"{memory.relative}: duplicate identity {name} (also {identities[name]})")
            else:
                identities[name] = memory.relative
    by_name = {}
    for memory in memories:
        aliases = memory.data.get("aliases", [])
        for identity in [memory.data.get("name"), *(aliases if isinstance(aliases, list) else [])]:
            if isinstance(identity, str):
                by_name[identity] = memory
    for memory in memories:
        for raw in WIKI_RE.findall(memory.body):
            name, heading = wiki_parts(raw)
            target = by_name.get(name)
            if target is None:
                issues.append(f"{memory.relative}: broken wiki link: {name}")
                continue
            if heading:
                headings = {heading_slug(value) for value in HEADING_RE.findall(target.body)}
                if heading_slug(heading) not in headings:
                    issues.append(f"{memory.relative}: broken wiki heading {heading!r} in {name}")
    hot_index = root / "MEMORY.md"
    if not hot_index.is_file():
        issues.append("MEMORY.md: file is missing")
    else:
        text = hot_index.read_text(encoding="utf-8")
        for raw in MD_LINK_RE.findall(text):
            target = markdown_target(root, hot_index, raw)
            if target is not None and not target.exists():
                issues.append(f"MEMORY.md: dead link: {raw}")
        for number, line in enumerate(text.splitlines(), 1):
            if line.startswith("- [") and len(line) > HOT_INDEX_MAX_LINE:
                issues.append(
                    f"MEMORY.md: line {number} is {len(line)} chars; maximum is {HOT_INDEX_MAX_LINE}"
                )
    return issues


def hot_index_links_to(root: Path, source: Path) -> bool:
    hot_index = root / "MEMORY.md"
    if not hot_index.is_file():
        return False
    for raw in MD_LINK_RE.findall(hot_index.read_text(encoding="utf-8")):
        if markdown_target(root, hot_index, raw) == source:
            return True
    return False


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


def append_audit(root: Path, *, action: str, path: str, reason: str,
                 before: str | None = None, after: str | None = None) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "path": path,
        "reason": reason,
    }
    if before is not None:
        record["before_sha256"] = before
    if after is not None:
        record["after_sha256"] = after
    audit = root / ".memory-workbench-audit.jsonl"
    existing = audit.read_text(encoding="utf-8") if audit.exists() else ""
    atomic_write(audit, existing + json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def body_sha(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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
        append_audit(root, action="candidate", path=target.relative_to(root).as_posix(),
                     reason=f"candidate created from {args.source}", after=body_sha(body))
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
        append_audit(root, action="promote", path=target.relative_to(root).as_posix(),
                     reason=args.reason, before=body_sha(memory.body), after=body_sha(memory.body))
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
        if hot_index_links_to(root, memory.path) and not args.allow_hot_link:
            raise MemoryError("MEMORY.md links to this memory; remove the hot link or use --allow-hot-link")
        target = root / "archive" / memory.path.name
        if target.exists():
            raise MemoryError(f"destination exists: {target.relative_to(root)}")
        data = dict(memory.data)
        data["status"] = "archived"
        data["archive_reason"] = args.reason
        atomic_write(target, render_memory(data, memory.body))
        memory.path.unlink()
        append_audit(root, action="archive", path=target.relative_to(root).as_posix(),
                     reason=args.reason, before=body_sha(memory.body), after=body_sha(memory.body))
        for path, text in expected_indexes(root).items():
            atomic_write(path, text, default_mode=0o644)
    print(target.relative_to(root))
    return 0


def cmd_update(args) -> int:
    root = resolve_root(args.root)
    body = read_body(args)
    if not body:
        raise MemoryError("body must not be empty")
    with memory_lock(root, exclusive=True, timeout=args.lock_timeout):
        matches = [
            memory for memory in load_memories(root)
            if args.name == memory.data.get("name") or args.name in (
                memory.data.get("aliases") if isinstance(memory.data.get("aliases"), list) else []
            )
        ]
        if len(matches) != 1:
            raise MemoryError(f"expected one memory named {args.name}, found {len(matches)}")
        memory = matches[0]
        data = dict(memory.data)
        data["updated"] = date.today().isoformat()
        atomic_write(memory.path, render_memory(data, body))
        append_audit(root, action="update", path=memory.relative, reason=args.reason,
                     before=body_sha(memory.body), after=body_sha(body))
    print(memory.relative)
    return 0


def cmd_audit(args) -> int:
    root = resolve_root(args.root)
    audit = root / ".memory-workbench-audit.jsonl"
    with memory_lock(root, exclusive=False, timeout=args.lock_timeout):
        if audit.exists():
            sys.stdout.write(audit.read_text(encoding="utf-8"))
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
    promote.add_argument("--reason", required=True)
    promote.set_defaults(func=cmd_promote)
    archive = sub.add_parser("archive", parents=[common])
    archive.add_argument("name")
    archive.add_argument("--reason", required=True)
    archive.add_argument("--allow-hot-link", action="store_true")
    archive.set_defaults(func=cmd_archive)
    update = sub.add_parser("update", parents=[common])
    update.add_argument("name")
    update.add_argument("--reason", required=True)
    update.add_argument("--body-file")
    update.set_defaults(func=cmd_update)
    audit = sub.add_parser("audit", parents=[common])
    audit.set_defaults(func=cmd_audit)
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
