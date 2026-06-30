#!/usr/bin/env python3
"""
wiki_gate.py — configurable gating conventions for Atlas memory retrieval.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_memory_search import search


SKILL_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = SKILL_ROOT / "gating_conventions.json"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_hits(query: str, patterns: list[str]) -> list[str]:
    hits: list[str] = []
    lowered = query.lower()
    for pattern in patterns:
        if re.search(pattern, query, flags=re.IGNORECASE) or pattern.lower() in lowered:
            hits.append(pattern)
    return list(dict.fromkeys(hits))


def fallback_queries(query: str, matched_signals: list[str]) -> list[str]:
    candidates: list[str] = []
    ascii_terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9\\-\\./\\+_]{1,}", query)
    for term in ascii_terms:
        if len(term) >= 3:
            candidates.append(term)
    for signal in matched_signals:
        if re.search(r"[A-Za-z]", signal):
            candidates.append(signal)
    deduped: list[str] = []
    for item in candidates:
        if item not in deduped:
            deduped.append(item)
    return deduped[:5]


def active_conventions(query: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for convention in config.get("conventions", []):
        matched_signals = detect_hits(query, convention.get("intent_patterns", []))
        is_active = bool(convention.get("always_on")) or bool(matched_signals)
        if not is_active:
            continue
        record = dict(convention)
        record["matched_signals"] = matched_signals
        active.append(record)
    active.sort(key=lambda item: int(item.get("priority", 0)), reverse=True)
    return active


def search_with_convention(query: str, convention: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    return search(
        query,
        limit=limit,
        domain=list(convention.get("domain_filter", [])),
        source_type=list(convention.get("source_type_filter", [])),
    )


def dedupe_results(results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(results, key=lambda r: float(r.get("score", 0)), reverse=True):
        key = str(item.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Route Atlas retrieval through configurable gating conventions")
    parser.add_argument("query", help="User query")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--search", action="store_true", help="Run constrained search for active conventions")
    parser.add_argument("--show-config", action="store_true", help="Print loaded gating config")
    args = parser.parse_args()

    config = load_config()
    if args.show_config:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return

    active = active_conventions(args.query, config)
    payload: dict[str, Any] = {
        "query": args.query,
        "active_conventions": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "always_on": item.get("always_on", False),
                "priority": item.get("priority", 0),
                "domain_filter": item.get("domain_filter", []),
                "source_type_filter": item.get("source_type_filter", []),
                "matched_signals": item.get("matched_signals", [])
            }
            for item in active
        ],
        "route": "search_active_conventions" if active else "skip_gated_memory",
        "reason": "one or more conventions activated" if active else "no gating convention matched"
    }

    if args.search and active:
        collected: list[dict[str, Any]] = []
        per_convention: list[dict[str, Any]] = []
        for convention in active:
            results = search_with_convention(args.query, convention, args.limit)
            used_fallback = None
            fallbacks: list[str] = []
            if not results:
                fallbacks = fallback_queries(args.query, convention.get("matched_signals", []))
                for candidate in fallbacks:
                    results = search_with_convention(candidate, convention, args.limit)
                    if results:
                        used_fallback = candidate
                        break
            per_convention.append(
                {
                    "id": convention.get("id"),
                    "name": convention.get("name"),
                    "matched_signals": convention.get("matched_signals", []),
                    "fallback_queries": fallbacks,
                    "fallback_used": used_fallback,
                    "results": results
                }
            )
            collected.extend(results)

        payload["per_convention"] = per_convention
        payload["results"] = dedupe_results(
            collected,
            limit=int(config.get("default_policy", {}).get("merge_results_limit", args.limit))
        )

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
