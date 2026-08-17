from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .core import MemoryError, memory_lock, resolve_root
from .lifecycle import collect_issues


def reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise MemoryError(f"mirror source contains a symlink: {path.relative_to(root)}")


def make_read_only(root: Path) -> None:
    for path in root.rglob("*"):
        mode = stat.S_IMODE(path.stat().st_mode)
        path.chmod(mode & ~0o222)
    root.chmod(stat.S_IMODE(root.stat().st_mode) & ~0o222)


def publish(source: Path, destination: Path, keep: int, lock_timeout: float) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    releases = destination / "releases"
    releases.mkdir(exist_ok=True)
    release_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = releases / release_name
    if target.exists():
        raise MemoryError(f"release already exists: {target}")
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=releases))
    try:
        staging.rmdir()
        with memory_lock(source, exclusive=False, timeout=lock_timeout):
            reject_symlinks(source)
            shutil.copytree(source, staging, symlinks=False, ignore=shutil.ignore_patterns(".memory-workbench.lock"))
        if not (staging / "MEMORY.md").is_file():
            raise MemoryError("mirror is missing MEMORY.md")
        issues = collect_issues(staging)
        if issues:
            raise MemoryError(f"mirror validation failed: {issues[0]}")
        make_read_only(staging)
        os.replace(staging, target)
        link = destination / ".current.new"
        link.unlink(missing_ok=True)
        link.symlink_to(Path("releases") / release_name)
        os.replace(link, destination / "current")
        old = sorted(path for path in releases.iterdir() if path.is_dir())[:-max(1, keep)]
        for path in old:
            for item in path.rglob("*"):
                if not item.is_symlink():
                    item.chmod(stat.S_IMODE(item.stat().st_mode) | 0o200)
            path.chmod(stat.S_IMODE(path.stat().st_mode) | 0o700)
            shutil.rmtree(path)
        return target
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Publish a validated immutable memory mirror")
    result.add_argument("--root", required=True)
    result.add_argument("--destination", required=True)
    result.add_argument("--keep", type=int, default=3)
    result.add_argument("--lock-timeout", type=float, default=30.0)
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.keep < 1:
            raise MemoryError("--keep must be at least 1")
        target = publish(resolve_root(args.root), Path(args.destination).expanduser().resolve(),
                         args.keep, args.lock_timeout)
        print(target)
        return 0
    except (MemoryError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
