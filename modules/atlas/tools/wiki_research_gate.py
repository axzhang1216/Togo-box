#!/usr/bin/env python3
"""
Backward-compatible wrapper for the paper gate convention.
Prefer `wiki_gate.py` for new usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_gate import active_conventions, fallback_queries, load_config, search_with_convention


def main() -> None:
    parser = argparse.ArgumentParser(description="Gate research-paper Atlas memory behind the paper gate convention")
    parser.add_argument("query", help="User query")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--search", action="store_true", help="Run search immediately if gate opens")
    parser.add_argument("--force", action="store_true", help="Force research-memory search even if gate stays closed")
    args = parser.parse_args()

    config = load_config()
    conventions = [
        item for item in active_conventions(args.query, config)
        if item.get("id") == "paper_gate_convention"
    ]
    convention = conventions[0] if conventions else None
    hits = list(convention.get("matched_signals", [])) if convention else []
    should_search = args.force or bool(convention)

    temp_convention = convention or {
        "domain_filter": ["科研", "论文"],
        "source_type_filter": [],
        "matched_signals": hits
    }

    payload = {
        "query": args.query,
        "route": "search_research_memory" if should_search else "skip_research_memory",
        "reason": "paper gate convention activated" if convention else "query does not look research/paper related",
        "matched_signals": hits,
        "domain_filter": list(temp_convention.get("domain_filter", [])) if should_search else [],
        "source_type_filter": list(temp_convention.get("source_type_filter", [])) if should_search else []
    }

    if args.search and should_search:
        results = search_with_convention(args.query, temp_convention, args.limit)
        payload["results"] = results
        if not results:
            fallbacks = fallback_queries(args.query, hits)
            payload["fallback_queries"] = fallbacks
            for candidate in fallbacks:
                results = search_with_convention(candidate, temp_convention, args.limit)
                if results:
                    payload["results"] = results
                    payload["fallback_used"] = candidate
                    break

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
