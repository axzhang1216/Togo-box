#!/usr/bin/env python3
"""
wiki_memory_search.py — Cheap first-pass retrieval over Wiki/retrieval_index.jsonl.

This intentionally searches the lightweight retrieval index, not the full Wiki
or raw sources. Use it to get a small candidate set before an LLM reads evidence.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_writer import WIKI_ROOT, normalize_text


RETRIEVAL_INDEX = WIKI_ROOT / "retrieval_index.jsonl"

ACTIVE_WEIGHT = {
    "active": 1.0,
    "resolved": 0.9,
    "uncertain": 0.72,
    "stale": 0.55,
    "superseded": 0.25,
    "deprecated": 0.2,
    "": 0.75,
}

FIELD_WEIGHTS = {
    "entities": 5.0,
    "aliases": 4.0,
    "direct_queries": 3.6,
    "indirect_queries": 3.0,
    "broader_topics": 2.4,
    "summary": 2.0,
    "note": 1.3,
    "memory_role": 0.8,
    "source_type": 1.2,
    "domain": 1.2,
}


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)] if str(value).strip() else []


def _tokens(text: str) -> List[str]:
    normalized = normalize_text(text)
    parts = normalized.split()
    tokens = set(parts)
    for seq in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(seq) >= 2:
            tokens.add(seq)
            for i in range(len(seq) - 1):
                tokens.add(seq[i:i + 2])
    return [t for t in tokens if t]


def load_index(path: Path = RETRIEVAL_INDEX) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _field_text(record: Dict[str, Any], field: str) -> str:
    value = record.get(field)
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value or "")


def _matches_filter(record: Dict[str, Any], name: str, allowed: Iterable[str]) -> bool:
    allowed_set = {normalize_text(v) for v in allowed if str(v).strip()}
    if not allowed_set:
        return True
    values = _as_list(record.get(name))
    normalized_values = {normalize_text(v) for v in values}
    return bool(allowed_set & normalized_values)


def score_record(record: Dict[str, Any], query: str) -> Tuple[float, Dict[str, List[str]]]:
    q = normalize_text(query)
    query_tokens = _tokens(query)
    matched: Dict[str, List[str]] = {}
    score = 0.0

    for field, weight in FIELD_WEIGHTS.items():
        text = _field_text(record, field)
        norm = normalize_text(text)
        hits = []
        if q and q in norm:
            score += weight * 3.0
            hits.append(query)
        for token in query_tokens:
            if token and token in norm:
                score += weight
                hits.append(token)
        if hits:
            matched[field] = sorted(set(hits))

    status = str(record.get("status", ""))
    score *= ACTIVE_WEIGHT.get(status, 0.75)
    return round(score, 3), matched


def search(
    query: str,
    limit: int = 10,
    domain: List[str] | None = None,
    source_type: List[str] | None = None,
    status: List[str] | None = None,
    include_inactive: bool = False,
) -> List[Dict[str, Any]]:
    records = load_index()
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

        score, matched = score_record(record, query)
        if score <= 0:
            continue
        results.append({
            "id": record.get("id"),
            "score": score,
            "summary": record.get("summary"),
            "source": record.get("source"),
            "source_type": record.get("source_type", ""),
            "domain": record.get("domain", []),
            "memory_role": record.get("memory_role"),
            "status": record.get("status"),
            "last_verified": record.get("last_verified"),
            "entities": record.get("entities", []),
            "matched_fields": matched,
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def llm_pack(results: List[Dict[str, Any]]) -> str:
    lines = []
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. {item.get('id')} score={item.get('score')} status={item.get('status')}")
        if item.get("domain"):
            lines.append(f"   domain: {', '.join(_as_list(item.get('domain')))}")
        if item.get("source_type"):
            lines.append(f"   source_type: {item.get('source_type')}")
        lines.append(f"   summary: {item.get('summary')}")
        if item.get("entities"):
            lines.append(f"   entities: {', '.join(_as_list(item.get('entities')))}")
        lines.append(f"   source: {item.get('source')}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the lightweight Wiki memory retrieval index")
    parser.add_argument("query", help="User query or recall clue")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--domain", action="append", default=[], help="Filter by broad domain, repeatable")
    parser.add_argument("--source-type", action="append", default=[], help="Filter by source type, repeatable")
    parser.add_argument("--status", action="append", default=[], help="Filter by memory status, repeatable")
    parser.add_argument("--include-inactive", action="store_true", help="Include deprecated/superseded memories")
    parser.add_argument("--llm-pack", action="store_true", help="Print compact text for an LLM reranker")
    args = parser.parse_args()

    results = search(
        args.query,
        limit=args.limit,
        domain=args.domain,
        source_type=args.source_type,
        status=args.status,
        include_inactive=args.include_inactive,
    )
    if args.llm_pack:
        print(llm_pack(results))
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
