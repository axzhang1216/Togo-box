#!/usr/bin/env python3
"""
wiki_search.py — Multi-strategy search for the Atlas memory graph.

Search strategy (from broad to specific):
  1. Exact title match
  2. Fuzzy title match (SequenceMatcher >= 0.86)
  3. Frontmatter field match (tags, project, authors, etc.)
  4. Full-text content search (body + frontmatter values)
  5. Graph neighbors (follow wikilinks from matched entities)

Each strategy returns results with a confidence score. Results are
deduplicated and ranked. Related entities are included when depth > 0.

Usage:
  python wiki_search.py "GEOS-Chem HEMCO config" [--type configs] [--depth 1]
  python wiki_search.py "ozone prediction" --type papers
  python wiki_search.py "张老师" --type people
  python wiki_search.py --context --purpose general
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_writer import (
    CONFIG, WIKI_ROOT, XREF, EDGES_PATH,
    parse_frontmatter, scan_entities, get_entity_dir,
    normalize_text, slugify, _load_edges, _edge_key,
)


# ---------------------------------------------------------------------------
# Search strategies
# ---------------------------------------------------------------------------

def _extract_wikilink_slugs(text: str) -> List[str]:
    """Extract [[slug]] targets from text."""
    return re.findall(r"\[\[([^\]|]+)", str(text))


def search_exact(entities: List[Dict], query: str) -> List[Dict]:
    """Strategy 1: Exact title/name match."""
    q = normalize_text(query)
    results = []
    for ent in entities:
        title = normalize_text(ent.get("title") or ent.get("name") or "")
        slug = normalize_text(ent.get("_slug", ""))
        if q == title or q == slug:
            results.append({
                "slug": ent["_slug"], "type": ent["_type"],
                "title": ent.get("title") or ent.get("name"),
                "score": 1.0, "strategy": "exact",
                "file": ent["_file"],
            })
    return results


def search_fuzzy(entities: List[Dict], query: str, threshold: float = 0.86) -> List[Dict]:
    """Strategy 2: Fuzzy title match."""
    from difflib import SequenceMatcher
    q = normalize_text(query)
    results = []
    for ent in entities:
        title = normalize_text(ent.get("title") or ent.get("name") or "")
        if not title:
            continue
        # Check if query is substring of title or vice versa
        if q in title or title in q:
            score = 0.95
        else:
            score = SequenceMatcher(None, q, title).ratio()
        if score >= threshold:
            results.append({
                "slug": ent["_slug"], "type": ent["_type"],
                "title": ent.get("title") or ent.get("name"),
                "score": round(score, 3), "strategy": "fuzzy",
                "file": ent["_file"],
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _extract_keywords(text: str) -> List[str]:
    """Extract keywords from text. Handles Chinese (char bigrams + full words) and English."""
    normalized = normalize_text(text)
    keywords = []
    # Split on spaces first
    for part in normalized.split():
        # For CJK: extract 2-char windows + the full word
        cjk_chars = re.findall(r"[一-鿿]+", part)
        for seq in cjk_chars:
            if len(seq) >= 2:
                # Add full sequence and all 2-char substrings
                keywords.append(seq)
                for i in range(len(seq) - 1):
                    keywords.append(seq[i:i+2])
            elif len(seq) == 1:
                keywords.append(seq)
        # For non-CJK: add as-is
        non_cjk = re.sub(r"[一-鿿]+", "", part).strip()
        if non_cjk:
            keywords.append(non_cjk)
    return list(set(keywords))


def search_field(entities: List[Dict], query: str) -> List[Dict]:
    """Strategy 3: Search specific frontmatter fields (supports Chinese keyword matching)."""
    q = query.lower()
    keywords = _extract_keywords(query)
    search_fields = ["tags", "tldr", "project", "authors", "venue",
                     "affiliation", "research_areas", "source", "variables",
                     "repo_url", "file_path", "description", "outcome"]
    results = []
    for ent in entities:
        for field in search_fields:
            val = ent.get(field)
            if val is None:
                continue
            if isinstance(val, list):
                val = " ".join(str(v) for v in val)
            val_str = str(val).lower()
            # Exact phrase match
            if q in val_str or val_str in q:
                results.append({
                    "slug": ent["_slug"], "type": ent["_type"],
                    "title": ent.get("title") or ent.get("name"),
                    "score": 0.8, "strategy": "field:" + field,
                    "file": ent["_file"], "matched_field": field,
                })
                break
            # Keyword match (for Chinese text without word boundaries)
            matched_kw = [kw for kw in keywords if kw in val_str]
            if len(matched_kw) >= 1:
                score = 0.6 + 0.2 * (len(matched_kw) / max(len(keywords), 1))
                results.append({
                    "slug": ent["_slug"], "type": ent["_type"],
                    "title": ent.get("title") or ent.get("name"),
                    "score": round(score, 3), "strategy": "field:" + field,
                    "file": ent["_file"], "matched_field": field,
                })
                break
    return results


def search_content(entities: List[Dict], query: str) -> List[Dict]:
    """Strategy 4: Full-text body search (supports Chinese keyword matching)."""
    q = query.lower()
    keywords = _extract_keywords(query)
    results = []
    for ent in entities:
        body = ent.get("_body", "").lower()
        # Exact phrase
        if q in body:
            count = body.count(q)
            score = min(0.75, 0.5 + count * 0.05)
            results.append({
                "slug": ent["_slug"], "type": ent["_type"],
                "title": ent.get("title") or ent.get("name"),
                "score": round(score, 3), "strategy": "content",
                "file": ent["_file"],
            })
        # Keyword match in body
        elif keywords:
            matched = [kw for kw in keywords if kw in body]
            if len(matched) >= 1:
                score = 0.4 + 0.3 * (len(matched) / max(len(keywords), 1))
                results.append({
                    "slug": ent["_slug"], "type": ent["_type"],
                    "title": ent.get("title") or ent.get("name"),
                    "score": round(score, 3), "strategy": "content",
                    "file": ent["_file"],
                })
    return results


def search_multi_keyword(entities: List[Dict], query: str) -> List[Dict]:
    """Strategy 5: Split query into keywords, score by match count."""
    keywords = normalize_text(query).split()
    if len(keywords) < 2:
        return []

    results = []
    for ent in entities:
        searchable = " ".join([
            str(ent.get("title", "")),
            str(ent.get("name", "")),
            str(ent.get("tldr", "")),
            str(ent.get("description", "")),
            ent.get("_body", ""),
        ]).lower()

        matched = sum(1 for kw in keywords if kw in searchable)
        if matched >= 2:
            score = 0.4 + (matched / len(keywords)) * 0.4
            results.append({
                "slug": ent["_slug"], "type": ent["_type"],
                "title": ent.get("title") or ent.get("name"),
                "score": round(score, 3), "strategy": "multi-keyword",
                "file": ent["_file"], "matched_keywords": matched,
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Relationship expansion
# ---------------------------------------------------------------------------

def expand_related(entities_map: Dict[str, Dict], slug: str, depth: int = 1) -> List[Dict]:
    """Follow wikilinks from an entity to find related entities."""
    if depth <= 0 or slug not in entities_map:
        return []

    ent = entities_map[slug]
    related = []
    visited = {slug}

    # Collect all wikilink targets from frontmatter + body
    targets = set()
    for field in ["project", "related_papers", "uses_methods", "uses_datasets",
                   "source_papers", "supersedes", "related_configs", "attendees",
                   "collaborators", "related_methods", "related_code",
                   "linked_idea", "evaluates_methods", "realizes_concepts"]:
        val = ent.get(field)
        if val:
            targets.update(_extract_wikilink_slugs(val))

    body = ent.get("_body", "")
    targets.update(_extract_wikilink_slugs(body))

    for target_slug in targets:
        if target_slug in visited or target_slug not in entities_map:
            continue
        visited.add(target_slug)
        target = entities_map[target_slug]
        related.append({
            "slug": target_slug,
            "type": target["_type"],
            "title": target.get("title") or target.get("name"),
            "score": 0.6,  # lower score for related
            "strategy": f"related-to:{slug}",
            "file": target["_file"],
            "via": slug,
        })

        # Recursive expansion
        if depth > 1:
            related.extend(expand_related(entities_map, target_slug, depth - 1))

    return related


# ---------------------------------------------------------------------------
# Graph neighbors
# ---------------------------------------------------------------------------

def graph_neighbors(slug: str, depth: int = 1) -> List[Dict]:
    """Find entities connected via graph edges."""
    edges = _load_edges()
    visited = {slug}
    frontier = [slug]
    results = []

    for _ in range(depth):
        next_frontier = []
        for node in frontier:
            for e in edges:
                neighbor = None
                if e["from"] == node:
                    neighbor = e["to"]
                elif e["to"] == node:
                    neighbor = e["from"]
                if neighbor and neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append(neighbor)
                    # Parse "type/slug" format
                    parts = neighbor.split("/", 1)
                    if len(parts) == 2:
                        results.append({
                            "slug": parts[1], "type": parts[0],
                            "title": parts[1], "score": 0.5,
                            "strategy": f"graph-edge:{e['type']}",
                            "via": slug,
                            "edge_type": e["type"],
                        })
        frontier = next_frontier

    return results


# ---------------------------------------------------------------------------
# Main search function
# ---------------------------------------------------------------------------

def search(query: str, entity_type: Optional[str] = None,
           depth: int = 1, limit: int = 10) -> List[Dict]:
    """Multi-strategy search. Returns ranked results."""
    entities = scan_entities(entity_type)
    entities_map = {e["_slug"]: e for e in entities}

    # Build result pool
    all_results: Dict[str, Dict] = {}  # slug -> best result

    def merge(results: List[Dict]):
        for r in results:
            slug = r["slug"]
            if slug not in all_results or r["score"] > all_results[slug]["score"]:
                all_results[slug] = r

    # Run strategies in order (early strategies are higher confidence)
    merge(search_exact(entities, query))
    merge(search_fuzzy(entities, query))
    merge(search_field(entities, query))
    merge(search_content(entities, query))
    merge(search_multi_keyword(entities, query))

    # Expand related entities for top matches
    top_slugs = sorted(all_results.keys(),
                       key=lambda s: all_results[s]["score"],
                       reverse=True)[:3]

    for slug in top_slugs:
        related = expand_related(entities_map, slug, depth)
        merge(related)

    # Also try graph neighbors for top matches
    for slug in top_slugs:
        graph_nb = graph_neighbors(slug, depth=1)
        for r in graph_nb:
            if r["slug"] in entities_map:
                r["file"] = entities_map[r["slug"]]["_file"]
                r["title"] = entities_map[r["slug"]].get("title") or r["slug"]
            merge(r)

    # Sort by score and return top N
    ranked = sorted(all_results.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:limit]


# ---------------------------------------------------------------------------
# Context compilation (wrapper around wiki_writer.compile_context)
# ---------------------------------------------------------------------------

def compile_context(purpose: str = "general", max_chars: int = 8000) -> str:
    """Compile purpose-specific context. Delegates to wiki_writer."""
    from wiki_writer import compile_context as _compile
    return _compile(purpose, max_chars)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Wiki multi-strategy search")
    parser.add_argument("query", nargs="?", default=None, help="Search query")
    parser.add_argument("--type", default=None, help="Restrict to entity type")
    parser.add_argument("--depth", type=int, default=1, help="Relationship expansion depth")
    parser.add_argument("--limit", type=int, default=10, help="Max results")
    parser.add_argument("--context", action="store_true", help="Compile context instead of search")
    parser.add_argument("--purpose", default="general", choices=["general", "research", "writing"])
    parser.add_argument("--max-chars", type=int, default=8000)
    args = parser.parse_args()

    if args.context:
        result = compile_context(args.purpose, args.max_chars)
        print(result)
    elif args.query:
        results = search(args.query, args.type, args.depth, args.limit)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
