from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .core import MemoryError, atomic_write, load_memories, memory_lock, resolve_root


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
WORD_RE = re.compile(r"[a-z0-9_./:-]+|[\u3400-\u9fff]", re.IGNORECASE)
CHUNK_TARGET = 1800
CHUNK_MAX = 3600
CACHE_SCHEMA = 1


@dataclass(frozen=True)
class Chunk:
    path: str
    heading: str
    index: int
    description: str
    text: str
    sha: str


def split_long(text: str, limit: int = CHUNK_MAX) -> list[str]:
    return [text[start:start + limit] for start in range(0, len(text), limit)] or [""]


def chunks_for(memory) -> list[Chunk]:
    sections: list[tuple[str, str]] = []
    matches = list(HEADING_RE.finditer(memory.body))
    if not matches:
        sections = [(memory.data.get("name", "Memory"), memory.body)]
    else:
        if matches[0].start() > 0:
            sections.append((memory.data.get("name", "Memory"), memory.body[:matches[0].start()]))
        for pos, match in enumerate(matches):
            end = matches[pos + 1].start() if pos + 1 < len(matches) else len(memory.body)
            sections.append((match.group(2).strip(), memory.body[match.end():end]))
    result: list[Chunk] = []
    for heading, content in sections:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
        pending = ""
        pieces: list[str] = []
        for paragraph in paragraphs:
            if len(paragraph) > CHUNK_MAX:
                if pending:
                    pieces.append(pending)
                    pending = ""
                pieces.extend(split_long(paragraph))
            elif pending and len(pending) + len(paragraph) + 2 > CHUNK_TARGET:
                pieces.append(pending)
                pending = paragraph
            else:
                pending = f"{pending}\n\n{paragraph}".strip()
        if pending:
            pieces.append(pending)
        for piece in pieces or [content.strip()]:
            if not piece:
                continue
            text = f"{memory.data.get('name', '')}\n{memory.data.get('description', '')}\n{heading}\n{piece}"
            result.append(Chunk(
                memory.relative,
                heading,
                len(result),
                str(memory.data.get("description", "")),
                piece,
                hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ))
    return result


def normalize(vector) -> list[float]:
    values = [float(item) for item in vector]
    norm = math.sqrt(sum(item * item for item in values))
    if not values or not math.isfinite(norm) or norm <= 0:
        raise MemoryError("embedding provider returned an invalid vector")
    return [item / norm for item in values]


class Provider:
    def __init__(self, name: str, model: str | None, endpoint: str | None, api_key_env: str):
        self.name = name
        self.model = model
        self.endpoint = endpoint
        self.api_key_env = api_key_env

    def embed(self, text: str, *, query: bool) -> list[float]:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise MemoryError(f"missing embedding credential in {self.api_key_env}")
        if self.name == "gemini":
            model = self.model or "gemini-embedding-001"
            endpoint = self.endpoint or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
            payload = {
                "model": f"models/{model}",
                "content": {"parts": [{"text": text}]},
                "taskType": "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
            }
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return normalize(json.load(response)["embedding"]["values"])
        if self.name == "openai-compatible":
            if not self.endpoint or not self.model:
                raise MemoryError("openai-compatible requires --endpoint and --model")
            request = urllib.request.Request(
                self.endpoint,
                data=json.dumps({"model": self.model, "input": text}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return normalize(json.load(response)["data"][0]["embedding"])
        raise MemoryError(f"unknown embedding provider: {self.name}")


def state_dir(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser()
    else:
        path = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "agent-memory-workbench"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def cache_path(directory: Path, include_private: bool) -> Path:
    return directory / ("semantic-with-private.json" if include_private else "semantic-public.json")


def current_chunks(root: Path, include_private: bool) -> list[Chunk]:
    memories = load_memories(root, include_private=include_private)
    if not include_private:
        memories = [memory for memory in memories if memory.data.get("visibility") != "private"]
    return [chunk for memory in memories for chunk in chunks_for(memory)]


def build_index(root: Path, directory: Path, provider: Provider, include_private: bool, lock_timeout: float) -> int:
    with memory_lock(root, exclusive=False, timeout=lock_timeout):
        chunks = current_chunks(root, include_private)
    records = []
    for chunk in chunks:
        vector = provider.embed(chunk.text, query=False)
        records.append({
            "path": chunk.path,
            "heading": chunk.heading,
            "index": chunk.index,
            "sha": chunk.sha,
            "vector": vector,
        })
    payload = {
        "schema": CACHE_SCHEMA,
        "provider": provider.name,
        "model": provider.model,
        "include_private": include_private,
        "records": records,
    }
    atomic_write(cache_path(directory, include_private), json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"indexed {len(records)} chunks")
    return 0


def tokens(text: str) -> set[str]:
    lowered = text.lower()
    base = WORD_RE.findall(lowered)
    chinese = "".join(char for char in lowered if "\u3400" <= char <= "\u9fff")
    grams = [chinese[i:i + size] for size in (2, 3) for i in range(max(0, len(chinese) - size + 1))]
    return set(base + grams)


def lexical_score(query: str, chunk: Chunk) -> float:
    query_tokens = tokens(query)
    if not query_tokens:
        return 0.0
    haystack = f"{chunk.path} {chunk.heading} {chunk.description} {chunk.text}".lower()
    matched = sum(1 for token in query_tokens if token in haystack)
    score = matched / len(query_tokens)
    if query.lower() in haystack:
        score += 0.5
    return score


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MemoryError(f"invalid semantic cache: {exc}") from exc
    if data.get("schema") != CACHE_SCHEMA or not isinstance(data.get("records"), list):
        raise MemoryError("unsupported semantic cache schema")
    return data


def search(root: Path, query: str, *, directory: Path, provider: Provider | None,
           include_private: bool, limit: int, lock_timeout: float) -> list[dict]:
    with memory_lock(root, exclusive=False, timeout=lock_timeout):
        chunks = current_chunks(root, include_private)
    semantic: dict[tuple[str, int, str], list[float]] = {}
    query_vector = None
    if provider:
        cache = load_cache(cache_path(directory, include_private))
        if cache and (cache.get("provider"), cache.get("model")) == (provider.name, provider.model):
            semantic = {
                (item["path"], int(item["index"]), item["sha"]): item["vector"]
                for item in cache["records"]
            }
            query_vector = provider.embed(query, query=True)
    ranked = []
    for chunk in chunks:
        lexical = lexical_score(query, chunk)
        vector = semantic.get((chunk.path, chunk.index, chunk.sha))
        semantic_score = sum(a * b for a, b in zip(query_vector, vector)) if query_vector and vector else 0.0
        score = lexical if query_vector is None else 0.25 * lexical + 0.75 * semantic_score
        if score > 0:
            ranked.append((score, lexical, semantic_score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    results = []
    seen = set()
    for score, lexical, semantic_score, chunk in ranked:
        if chunk.path in seen:
            continue
        seen.add(chunk.path)
        results.append({
            "score": round(score, 6),
            "lexical_score": round(lexical, 6),
            "semantic_score": round(semantic_score, 6),
            "path": chunk.path,
            "heading": chunk.heading,
            "description": chunk.description,
            "excerpt": chunk.text[:600].replace("\n", " "),
        })
        if len(results) >= limit:
            break
    return results


def add_common(parser):
    parser.add_argument("--root")
    parser.add_argument("--state-dir")
    parser.add_argument("--include-private", action="store_true")
    parser.add_argument("--provider", choices=("none", "gemini", "openai-compatible"), default="none")
    parser.add_argument("--model")
    parser.add_argument("--endpoint")
    parser.add_argument("--api-key-env", default="EMBEDDING_API_KEY")
    parser.add_argument("--lock-timeout", type=float, default=10.0)


def make_provider(args) -> Provider | None:
    return None if args.provider == "none" else Provider(args.provider, args.model, args.endpoint, args.api_key_env)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Hybrid search for file-first agent memory")
    sub = root.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index")
    add_common(index)
    search_parser = sub.add_parser("search")
    add_common(search_parser)
    search_parser.add_argument("query", nargs="*")
    search_parser.add_argument("--stdin-query", action="store_true")
    search_parser.add_argument("-k", "--limit", type=int, default=5)
    search_parser.add_argument("--json", action="store_true")
    return root


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        root = resolve_root(args.root)
        directory = state_dir(args.state_dir)
        provider = make_provider(args)
        if args.command == "index":
            if provider is None:
                raise MemoryError("semantic indexing requires an embedding provider")
            return build_index(root, directory, provider, args.include_private, args.lock_timeout)
        query = sys.stdin.read().strip() if args.stdin_query else " ".join(args.query).strip()
        if not query:
            raise MemoryError("search query is empty")
        results = search(root, query, directory=directory, provider=provider,
                         include_private=args.include_private, limit=args.limit,
                         lock_timeout=args.lock_timeout)
        if args.json:
            print(json.dumps(results, ensure_ascii=False))
        else:
            for result in results:
                print(f"{result['score']:.3f}  {result['path']} [{result['heading']}]\n       {result['excerpt']}")
        return 0
    except (MemoryError, OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
