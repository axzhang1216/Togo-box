#!/usr/bin/env python3
"""
wiki_memory_vector.py — Embedding index for Wiki/retrieval_index.jsonl.

The vector index is derived data. Rebuild it whenever retrieval_index.jsonl
changes. It requires an OpenAI-compatible embeddings API key.
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_memory_search import ACTIVE_WEIGHT, _as_list, _matches_filter, load_index
from wiki_writer import WIKI_ROOT


VECTOR_INDEX = WIKI_ROOT / "retrieval_vectors.jsonl"
DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


def memory_text(record: Dict[str, Any]) -> str:
    parts = [
        record.get("summary", ""),
        " ".join(_as_list(record.get("entities"))),
        " ".join(_as_list(record.get("direct_queries"))),
        " ".join(_as_list(record.get("indirect_queries"))),
        " ".join(_as_list(record.get("aliases"))),
        " ".join(_as_list(record.get("broader_topics"))),
        " ".join(_as_list(record.get("domain"))),
        str(record.get("source_type", "")),
    ]
    return "\n".join(p for p in parts if str(p).strip())


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embedding_config() -> Tuple[str, str, str]:
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("WIKI_EMBEDDING_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("WIKI_EMBEDDING_BASE_URL") or DEFAULT_BASE_URL
    model = os.environ.get("OPENAI_EMBEDDING_MODEL") or os.environ.get("WIKI_EMBEDDING_MODEL") or DEFAULT_MODEL
    if not api_key:
        raise RuntimeError(
            "Missing embedding API key. Set OPENAI_API_KEY or WIKI_EMBEDDING_API_KEY."
        )
    return api_key, base_url.rstrip("/"), model


def embed_texts(texts: List[str], api_key: str, base_url: str, model: str) -> List[List[float]]:
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Embedding API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Embedding API request failed: {exc}") from exc

    data = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
    vectors = [item.get("embedding") for item in data]
    if len(vectors) != len(texts) or any(not isinstance(v, list) for v in vectors):
        raise RuntimeError("Embedding API returned malformed embedding data.")
    return vectors


def write_vectors(records: List[Dict[str, Any]], vectors: List[List[float]], model: str, base_url: str) -> None:
    VECTOR_INDEX.parent.mkdir(parents=True, exist_ok=True)
    with open(VECTOR_INDEX, "w", encoding="utf-8") as f:
        for record, vector in zip(records, vectors):
            text = memory_text(record)
            item = {
                "id": record.get("id"),
                "note": record.get("note"),
                "fragment": record.get("fragment"),
                "model": model,
                "base_url": base_url,
                "text_hash": text_hash(text),
                "dimension": len(vector),
                "vector": vector,
            }
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def build(batch_size: int = 64) -> Dict[str, Any]:
    api_key, base_url, model = embedding_config()
    records = load_index()
    texts = [memory_text(r) for r in records]
    vectors: List[List[float]] = []
    for i in range(0, len(texts), batch_size):
        vectors.extend(embed_texts(texts[i:i + batch_size], api_key, base_url, model))
    write_vectors(records, vectors, model, base_url)
    return {
        "ok": True,
        "records": len(records),
        "model": model,
        "base_url": base_url,
        "vector_index": str(VECTOR_INDEX),
    }


def load_vectors() -> Dict[str, Dict[str, Any]]:
    if not VECTOR_INDEX.exists():
        raise RuntimeError(f"Vector index does not exist: {VECTOR_INDEX}. Run build first.")
    vectors = {}
    with open(VECTOR_INDEX, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            vectors[item["id"]] = item
    return vectors


def cosine_similarity(query_vector: Iterable[float], item_vector: Iterable[float]) -> float:
    import numpy as np

    q = np.asarray(list(query_vector), dtype=np.float32)
    v = np.asarray(list(item_vector), dtype=np.float32)
    denom = float(np.linalg.norm(q) * np.linalg.norm(v))
    if denom == 0:
        return 0.0
    return float(np.dot(q, v) / denom)


def search(
    query: str,
    limit: int = 10,
    domain: List[str] | None = None,
    source_type: List[str] | None = None,
    status: List[str] | None = None,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    api_key, base_url, model = embedding_config()
    records = load_index()
    vectors = load_vectors()
    query_vector = embed_texts([query], api_key, base_url, model)[0]

    results = []
    for record in records:
        if not include_inactive and record.get("status") in {"deprecated", "superseded"}:
            continue
        if not _matches_filter(record, "domain", domain or []):
            continue
        if not _matches_filter(record, "source_type", source_type or []):
            continue
        if not _matches_filter(record, "status", status or []):
            continue

        item = vectors.get(record.get("id"))
        if not item:
            continue
        current_hash = text_hash(memory_text(record))
        stale_vector = item.get("text_hash") != current_hash or item.get("model") != model
        similarity = cosine_similarity(query_vector, item.get("vector", []))
        weighted_score = similarity * ACTIVE_WEIGHT.get(str(record.get("status", "")), 0.75)
        results.append({
            "id": record.get("id"),
            "score": round(weighted_score, 6),
            "similarity": round(similarity, 6),
            "stale_vector": stale_vector,
            "summary": record.get("summary"),
            "source": record.get("source"),
            "source_type": record.get("source_type", ""),
            "domain": record.get("domain", []),
            "memory_role": record.get("memory_role"),
            "status": record.get("status"),
            "last_verified": record.get("last_verified"),
            "entities": record.get("entities", []),
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/search Wiki memory embedding vectors")
    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", help="Build Wiki/retrieval_vectors.jsonl")
    p_build.add_argument("--batch-size", type=int, default=64)

    p_search = sub.add_parser("search", help="Vector search over Wiki/retrieval_vectors.jsonl")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--domain", action="append", default=[])
    p_search.add_argument("--source-type", action="append", default=[])
    p_search.add_argument("--status", action="append", default=[])
    p_search.add_argument("--include-inactive", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(batch_size=args.batch_size)
        elif args.command == "search":
            result = search(
                args.query,
                limit=args.limit,
                domain=args.domain,
                source_type=args.source_type,
                status=args.status,
                include_inactive=args.include_inactive,
            )
        else:
            parser.print_help()
            sys.exit(1)
    except RuntimeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(2)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
