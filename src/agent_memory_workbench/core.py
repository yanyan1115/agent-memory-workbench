from __future__ import annotations

import contextlib
import fcntl
import math
import os
import re
import stat
import tempfile
import time
from urllib.parse import unquote
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml


AREAS = ("active", "archive", "private")
GENERATED_MARKER = "<!-- memory-workbench:generated; do not edit -->"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
WIKI_RE = re.compile(r"\[\[([^\]]+)\]\]")
MD_LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
HOT_INDEX_MAX_LINE = 200


class MemoryError(RuntimeError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise MemoryError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


@dataclass(frozen=True)
class Memory:
    path: Path
    relative: str
    data: dict
    body: str


def resolve_root(value: str | None) -> Path:
    raw = value or os.environ.get("MEMORY_WORKBENCH_ROOT")
    if not raw:
        raise MemoryError("set --root or MEMORY_WORKBENCH_ROOT")
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise MemoryError(f"memory root is not a directory: {root}")
    return root


def validate_timeout(value: float) -> float:
    if not math.isfinite(value) or value < 0 or value > 3600:
        raise MemoryError("lock timeout must be finite and between 0 and 3600 seconds")
    return value


def safe_path(root: Path, value: str | Path, *, must_exist: bool = False) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise MemoryError(f"path escapes memory root: {value}") from exc
    current = root
    for part in resolved.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise MemoryError(f"symlink paths are not allowed: {current}")
    if must_exist and not resolved.exists():
        raise MemoryError(f"path does not exist: {value}")
    return resolved


@contextlib.contextmanager
def memory_lock(root: Path, *, exclusive: bool, timeout: float = 10.0) -> Iterator[None]:
    timeout = validate_timeout(timeout)
    path = root / ".memory-workbench.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MemoryError(f"lock timeout after {timeout:g}s")
                time.sleep(0.05)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_write(path: Path, text: str, *, default_mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else default_mode
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def parse_memory(path: Path, root: Path) -> Memory:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise MemoryError("missing YAML frontmatter")
    try:
        _, frontmatter, body = text.split("---", 2)
    except ValueError as exc:
        raise MemoryError("unterminated YAML frontmatter") from exc
    try:
        data = yaml.load(frontmatter, Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise MemoryError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise MemoryError("frontmatter must be a mapping")
    return Memory(path, path.relative_to(root).as_posix(), data, body.strip())


def render_memory(data: dict, body: str) -> str:
    frontmatter = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{frontmatter}\n---\n\n{body.strip()}\n"


def iter_memory_paths(root: Path, *, candidates: bool = False, include_private: bool = True):
    bases = list(AREAS if include_private else ("active", "archive"))
    if candidates:
        bases.append("inbox")
    for area in bases:
        base = root / area
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.name in {"README.md", "INDEX.md"}:
                continue
            yield safe_path(root, path, must_exist=True)


def load_memories(root: Path, *, candidates: bool = False, include_private: bool = True):
    return [parse_memory(path, root) for path in iter_memory_paths(
        root, candidates=candidates, include_private=include_private
    )]


def validate_memory(memory: Memory) -> list[str]:
    issues: list[str] = []
    data = memory.data
    for field in ("schema_version", "name", "description", "type"):
        if field not in data:
            issues.append(f"missing field: {field}")
    if data.get("schema_version") != 1:
        issues.append("schema_version must be 1")
    name = data.get("name")
    if not isinstance(name, str) or not SLUG_RE.fullmatch(name):
        issues.append("name must be a lowercase hyphenated slug")
    for field in ("description", "type"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            issues.append(f"{field} must be a non-empty string")
    for field in ("aliases", "tags"):
        value = data.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            issues.append(f"{field} must be a list of strings")
    if not memory.body:
        issues.append("body must not be empty")
    expected_name = memory.path.stem.replace("_", "-")
    if isinstance(name, str) and name != expected_name:
        issues.append(f"name must match filename: expected {expected_name}")
    is_private_path = memory.relative.startswith("private/") or memory.relative.startswith("inbox/private/")
    if is_private_path and data.get("visibility") != "private":
        issues.append("private paths require visibility: private")
    if not is_private_path and data.get("visibility") == "private":
        issues.append("private memories must live under private/")
    return issues


def heading_slug(value: str) -> str:
    value = re.sub(r"[`*_~]", "", value.strip().lower())
    value = re.sub(r"[^\w\-\s]", "", value, flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", value).strip("-")


def wiki_parts(raw: str) -> tuple[str, str | None]:
    target = raw.split("|", 1)[0].strip()
    if "#" in target:
        name, heading = target.split("#", 1)
        return name.strip(), unquote(heading.strip())
    return target, None


def markdown_target(root: Path, source: Path, raw: str) -> Path | None:
    target = raw.strip().split(maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = unquote(target.split("#", 1)[0])
    try:
        return safe_path(root, source.parent / target)
    except MemoryError:
        return Path("/__invalid_root_escape__")
