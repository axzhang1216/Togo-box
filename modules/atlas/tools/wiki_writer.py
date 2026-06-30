#!/usr/bin/env python3
"""
wiki_writer.py — Deterministic writer for the Atlas memory graph.

Design principles (inherited from mindflow + omegaWiki):
- LLMs do NOT write files directly; this script is the sole write path
- YAML frontmatter is the structured layer; Markdown body is the document layer
- Every write rebuilds the memory index
- Bidirectional links are mandatory
- Atomic writes (.tmp + .replace) for crash safety
- Schema validation on every write

Commands:
  write       Create a new entity (validates schema, atomic write)
  update      Update entity frontmatter (validates schema, atomic write)
  link        Add a bidirectional link
  unlink      Remove a link
  add-edge    Add a semantic graph edge to edges.jsonl
  resolve     Fuzzy match an entity
  check-dup   Check for duplicate entity
  lint        Run structural linter (broken links, orphans, schema)
  context     Compile purpose-specific context summary
  rebuild-index  Rebuild memory index
  list        List entities
  stats       Print wiki statistics
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_ROOT.parent.parent
CONFIG_PATH = SKILL_ROOT / "wiki.json"
DEFAULT_WIKI_ROOT = REPO_ROOT / "output" / "atlas-wiki"
DEFAULT_MEMORY_INDEX_PATH = DEFAULT_WIKI_ROOT / "wiki_index.md"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def resolve_config_path(value: str | None, default: Path) -> Path:
    if not value:
        return default.resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = (SKILL_ROOT / candidate).resolve()
    return candidate


def load_xref() -> dict:
    if XREF_PATH.exists():
        with open(XREF_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {"rules": [], "terminal_targets": []}


CONFIG = load_config()
WIKI_ROOT = resolve_config_path(CONFIG.get("wiki_root"), DEFAULT_WIKI_ROOT)
MEMORY_INDEX_PATH = resolve_config_path(CONFIG.get("memory_index_path"), DEFAULT_MEMORY_INDEX_PATH)
XREF_PATH = WIKI_ROOT / "xref.yaml"
EDGES_PATH = WIKI_ROOT / "graph" / "edges.jsonl"
XREF = load_xref()
FUZZY_THRESHOLD = CONFIG.get("fuzzy_match_threshold", 0.86)


# ---------------------------------------------------------------------------
# Atomic write (crash safety: .tmp + .replace)
# ---------------------------------------------------------------------------

def atomic_write(file_path: Path, content: str) -> None:
    """Write content atomically via .tmp + .replace()."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        shutil.move(tmp_path, str(file_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# YAML frontmatter helpers
# ---------------------------------------------------------------------------

def parse_frontmatter(content: str) -> Tuple[dict, str]:
    """Parse YAML frontmatter + body from a markdown file."""
    if content.startswith("---"):
        match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)(.*)$", content, re.DOTALL)
        if match:
            fm = yaml.safe_load(match.group(1)) or {}
            body = match.group(2).strip()
            return fm, body
    return {}, content.strip()


def serialize_frontmatter(fm: dict, body: str) -> str:
    """Serialize frontmatter + body to markdown."""
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return f"---\n{fm_str}---\n\n{body}\n"


def get_entity_dir(entity_type: str) -> Path:
    type_info = CONFIG.get("entity_types", {}).get(entity_type, {})
    dir_name = type_info.get("dir", entity_type)
    return WIKI_ROOT / dir_name


def get_tag_for_type(entity_type: str) -> str:
    return CONFIG.get("entity_types", {}).get(entity_type, {}).get("tag", f"wiki/{entity_type}")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_entity(entity_type: str, frontmatter: dict) -> List[str]:
    """Validate frontmatter against wiki.json schema. Returns list of errors."""
    errors = []
    type_info = CONFIG.get("entity_types", {}).get(entity_type, {})
    if not type_info:
        errors.append(f"Unknown entity type: {entity_type}")
        return errors

    # Check required fields
    for field in type_info.get("key_fields", []):
        if field not in frontmatter or frontmatter[field] is None or frontmatter[field] == "":
            errors.append(f"Missing required field: {field}")

    # Check kind_values enum
    kind_values = type_info.get("kind_values")
    if kind_values and "kind" in frontmatter and frontmatter["kind"] is not None:
        if frontmatter["kind"] not in kind_values:
            errors.append(f"Invalid kind: '{frontmatter['kind']}' (must be one of: {', '.join(kind_values)})")

    return errors


# ---------------------------------------------------------------------------
# Text normalization (from mindflow_resolution.py)
# ---------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    lowered = (text or "").strip().lower()
    lowered = re.sub(r"[^\w一-鿿]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def slugify(text: str) -> str:
    slug = normalize_text(text)
    slug = slug.replace(" ", "-")
    slug = re.sub(r"[^a-z0-9一-鿿-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled"


# ---------------------------------------------------------------------------
# Entity resolution (adapted from mindflow_resolution.py)
# ---------------------------------------------------------------------------

def scan_entities(entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Scan wiki directories and return all entities with metadata."""
    entities = []
    type_dirs = CONFIG.get("entity_types", {})
    types_to_scan = [entity_type] if entity_type else list(type_dirs.keys())

    for etype in types_to_scan:
        info = type_dirs.get(etype, {})
        entity_dir = WIKI_ROOT / info.get("dir", etype)
        if not entity_dir.exists():
            continue
        for f in entity_dir.glob("*.md"):
            content = f.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(content)
            fm["_file"] = str(f)
            fm["_type"] = etype
            fm["_slug"] = f.stem
            fm["_body"] = body
            entities.append(fm)
    return entities


def resolve_entity(query: str, entity_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fuzzy match an entity by query. Returns None if ambiguous or no match."""
    entities = scan_entities(entity_type)
    if not entities:
        return None

    query_normalized = normalize_text(query)
    ranked = []

    for ent in entities:
        title = ent.get("title") or ent.get("name") or ""
        title_normalized = normalize_text(title)
        if not title_normalized:
            continue

        if title_normalized in query_normalized or query_normalized in title_normalized:
            ranked.append({
                "slug": ent["_slug"], "type": ent["_type"], "title": title,
                "score": 1.0, "match_type": "exact", "file": ent["_file"],
            })
            continue

        score = SequenceMatcher(None, query_normalized, title_normalized).ratio()
        if score >= FUZZY_THRESHOLD:
            ranked.append({
                "slug": ent["_slug"], "type": ent["_type"], "title": title,
                "score": round(score, 3), "match_type": "fuzzy", "file": ent["_file"],
            })

    if not ranked:
        return None
    ranked.sort(key=lambda x: x["score"], reverse=True)

    exact = [r for r in ranked if r["score"] == 1.0]
    if exact:
        exact.sort(key=lambda r: (bool(re.search(r"-\d+$", r["slug"])), len(r["slug"]), r["slug"]))
        return exact[0]

    if len(ranked) > 1 and ranked[0]["score"] == ranked[1]["score"]:
        return None
    return ranked[0]


def check_duplicate(title: str, entity_type: str) -> Optional[Dict[str, Any]]:
    return resolve_entity(title, entity_type)


# ---------------------------------------------------------------------------
# Write operations (with schema validation + atomic writes)
# ---------------------------------------------------------------------------

def write_entity(entity_type: str, slug: str, frontmatter: dict, body: str = "") -> dict:
    """Create a new entity with schema validation and atomic write."""
    entity_dir = get_entity_dir(entity_type)
    entity_dir.mkdir(parents=True, exist_ok=True)

    file_path = entity_dir / f"{slug}.md"
    if file_path.exists():
        return {"ok": False, "error": f"Entity already exists: {entity_type}/{slug}.md"}

    # Ensure required frontmatter fields
    tag = get_tag_for_type(entity_type)
    if "tags" not in frontmatter:
        frontmatter["tags"] = [tag]
    elif tag not in frontmatter.get("tags", []):
        frontmatter["tags"] = list(frontmatter["tags"]) + [tag]

    if "slug" not in frontmatter:
        frontmatter["slug"] = slug

    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    if "date_added" not in frontmatter:
        frontmatter["date_added"] = now

    # Schema validation
    errors = validate_entity(entity_type, frontmatter)
    if errors:
        return {"ok": False, "errors": errors}

    content = serialize_frontmatter(frontmatter, body)
    atomic_write(file_path, content)

    return {"ok": True, "file": str(file_path), "type": entity_type, "slug": slug}


def update_entity(slug: str, updates: dict) -> dict:
    """Update fields in an existing entity's frontmatter."""
    entity = resolve_entity(slug)
    if not entity:
        for etype in CONFIG.get("entity_types", {}):
            fpath = get_entity_dir(etype) / f"{slug}.md"
            if fpath.exists():
                entity = {"slug": slug, "type": etype, "file": str(fpath)}
                break
    if not entity:
        return {"ok": False, "error": f"Entity not found: {slug}"}

    file_path = Path(entity["file"])
    content = file_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    for k, v in updates.items():
        if not k.startswith("_"):
            fm[k] = v

    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    fm["date_updated"] = now

    # Schema validation
    entity_type = entity.get("type", entity.get("_type", ""))
    errors = validate_entity(entity_type, fm)
    if errors:
        return {"ok": False, "errors": errors}

    new_content = serialize_frontmatter(fm, body)
    atomic_write(file_path, new_content)

    return {"ok": True, "file": str(file_path), "slug": slug, "updated_fields": list(updates.keys())}


def find_entity_file(slug: str) -> Optional[Tuple[str, Path]]:
    for etype in CONFIG.get("entity_types", {}):
        fpath = get_entity_dir(etype) / f"{slug}.md"
        if fpath.exists():
            return (etype, fpath)
    return None


def add_link(from_slug: str, to_slug: str, field: str) -> dict:
    """Add a bidirectional link between two entities."""
    from_info = find_entity_file(from_slug)
    to_info = find_entity_file(to_slug)

    if not from_info:
        return {"ok": False, "error": f"Source entity not found: {from_slug}"}
    if not to_info:
        return {"ok": False, "error": f"Target entity not found: {to_slug}"}

    rel_config = CONFIG.get("relationships", {}).get(field, {})
    link_type = rel_config.get("link_type", "list_link")
    reverse_section = rel_config.get("reverse_section")

    # Update forward link
    from_path = from_info[1]
    content = from_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    link_value = f"[[{to_slug}]]"
    if link_type == "list_link":
        existing = fm.get(field, [])
        if isinstance(existing, str):
            existing = [s.strip() for s in existing.split(",") if s.strip()]
        if link_value not in existing:
            existing.append(link_value)
        fm[field] = existing
    else:
        fm[field] = link_value

    atomic_write(from_path, serialize_frontmatter(fm, body))

    # Update reverse link
    to_path = to_info[1]
    to_content = to_path.read_text(encoding="utf-8")
    to_fm, to_body = parse_frontmatter(to_content)

    if reverse_section:
        backlink = f"- [[{from_slug}]]"
        if reverse_section in to_body:
            if backlink not in to_body:
                idx = to_body.index(reverse_section) + len(reverse_section)
                next_newline = to_body.index("\n", idx) if "\n" in to_body[idx:] else len(to_body)
                to_body = to_body[:next_newline + 1] + backlink + "\n" + to_body[next_newline + 1:]
        else:
            to_body += f"\n\n{reverse_section}\n{backlink}\n"

    atomic_write(to_path, serialize_frontmatter(to_fm, to_body))

    return {"ok": True, "from": from_slug, "to": to_slug, "field": field}


def remove_link(from_slug: str, to_slug: str, field: str) -> dict:
    from_info = find_entity_file(from_slug)
    if not from_info:
        return {"ok": False, "error": f"Source entity not found: {from_slug}"}

    from_path = from_info[1]
    content = from_path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    link_value = f"[[{to_slug}]]"
    existing = fm.get(field, [])
    if isinstance(existing, list) and link_value in existing:
        existing.remove(link_value)
        fm[field] = existing
        atomic_write(from_path, serialize_frontmatter(fm, body))
        return {"ok": True, "from": from_slug, "to": to_slug, "field": field}
    elif isinstance(existing, str) and fm.get(field) == link_value:
        fm[field] = ""
        atomic_write(from_path, serialize_frontmatter(fm, body))
        return {"ok": True, "from": from_slug, "to": to_slug, "field": field}

    return {"ok": False, "error": f"Link not found: {from_slug} --{field}--> {to_slug}"}


# ---------------------------------------------------------------------------
# Graph edges (edges.jsonl)
# ---------------------------------------------------------------------------

def _load_edges() -> List[dict]:
    """Load all edges from edges.jsonl."""
    if not EDGES_PATH.exists():
        return []
    edges = []
    with open(EDGES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                edges.append(json.loads(line))
    return edges


def _edge_key(edge: dict) -> Tuple[str, str, str]:
    """Compute dedup key. Sort endpoints for symmetric-like comparison."""
    return (edge.get("from", ""), edge.get("to", ""), edge.get("type", ""))


def add_edge(from_id: str, to_id: str, edge_type: str, evidence: str = "",
             confidence: Optional[str] = None) -> dict:
    """Add a semantic edge to graph/edges.jsonl with dedup."""
    # Validate
    valid_types = ["same_problem_as", "similar_method_to", "builds_on", "challenges",
                   "introduces_concept", "uses_concept", "extends_concept", "critiques_concept",
                   "supports", "contradicts", "tested_by", "invalidates",
                   "addresses_gap", "inspired_by", "derived_from", "cites"]
    if edge_type not in valid_types:
        return {"ok": False, "error": f"Unknown edge type: {edge_type}"}

    edge = {"from": from_id, "to": to_id, "type": edge_type}
    if evidence:
        edge["evidence"] = evidence
    if confidence:
        valid_conf = ["high", "medium", "low"]
        if confidence not in valid_conf:
            return {"ok": False, "error": f"Invalid confidence: {confidence}"}
        edge["confidence"] = confidence
    edge["date"] = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    # Dedup
    edges = _load_edges()
    existing_keys = {_edge_key(e) for e in edges}
    if _edge_key(edge) in existing_keys:
        return {"ok": True, "status": "exists", "from": from_id, "to": to_id, "type": edge_type}

    # Append
    EDGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EDGES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    return {"ok": True, "status": "created", "from": from_id, "to": to_id, "type": edge_type}


def get_neighbors(node_id: str, depth: int = 1) -> List[dict]:
    """BFS graph traversal from a node."""
    edges = _load_edges()
    visited = {node_id}
    frontier = [node_id]
    result = []

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
                    result.append(e)
        frontier = next_frontier

    return result


# ---------------------------------------------------------------------------
# Linter (standalone check, not full wiki_lint.py)
# ---------------------------------------------------------------------------

def lint_wiki() -> List[dict]:
    """Quick structural lint: broken links, orphans, missing fields, schema."""
    issues = []
    entities = scan_entities()
    all_slugs = {e["_slug"] for e in entities}

    # Build incoming links map
    incoming: Dict[str, int] = {s: 0 for s in all_slugs}

    for ent in entities:
        slug = ent["_slug"]
        body = ent.get("_body", "")

        # Check broken wikilinks
        for match in re.finditer(r"\[\[([^\]|]+)", body):
            target = match.group(1).strip()
            if target not in all_slugs:
                issues.append({"level": "yellow", "category": "broken_link",
                               "file": ent["_file"], "message": f"Broken link: [[{target}]]"})
            else:
                incoming[target] = incoming.get(target, 0) + 1

        # Check frontmatter link fields
        for field in ["project", "related_papers", "uses_methods", "uses_datasets",
                       "source_papers", "supersedes", "related_configs", "attendees",
                       "collaborators", "related_methods", "related_code"]:
            val = ent.get(field)
            if isinstance(val, str) and val.startswith("[["):
                target = val.strip("[]")
                if target not in all_slugs:
                    issues.append({"level": "yellow", "category": "broken_link",
                                   "file": ent["_file"], "message": f"Broken frontmatter link: {field} -> [[{target}]]"})
                else:
                    incoming[target] = incoming.get(target, 0) + 1
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.startswith("[["):
                        target = item.strip("[]")
                        if target not in all_slugs:
                            issues.append({"level": "yellow", "category": "broken_link",
                                           "file": ent["_file"], "message": f"Broken frontmatter link: {field} -> [[{target}]]"})
                        else:
                            incoming[target] = incoming.get(target, 0) + 1

        # Check schema validation
        etype = ent["_type"]
        errors = validate_entity(etype, ent)
        for err in errors:
            issues.append({"level": "red", "category": "schema", "file": ent["_file"], "message": err})

    # Check orphan pages
    for slug in all_slugs:
        if incoming.get(slug, 0) == 0:
            issues.append({"level": "blue", "category": "orphan",
                           "file": "", "message": f"Orphan page: {slug} (no incoming links)"})

    return issues


# ---------------------------------------------------------------------------
# Context compiler (from omegaWiki's compile_context)
# ---------------------------------------------------------------------------

CONTEXT_BUDGETS = {
    "general": (2000, 1000, 500, 2000, 500, 1000, 500),
    "research": (3000, 2000, 1000, 3000, 1000, 1500, 1000),
    "writing": (1500, 500, 300, 3000, 500, 500, 300),
}


def compile_context(purpose: str = "general", max_chars: int = 8000) -> str:
    """Compile a purpose-specific context summary from wiki entities."""
    budgets = CONTEXT_BUDGETS.get(purpose, CONTEXT_BUDGETS["general"])
    entities = scan_entities()
    now = datetime.now(timezone(timedelta(hours=8)))
    sections = []
    total_chars = 0

    def add_section(title: str, content: str, budget: int):
        nonlocal total_chars
        if total_chars >= max_chars:
            return
        truncated = content[:budget]
        if len(content) > budget:
            truncated += "\n... (truncated)"
        sections.append(f"## {title}\n{truncated}")
        total_chars += len(truncated) + len(title) + 4

    # 1. Active decisions
    decisions = [e for e in entities if e["_type"] == "decisions" and e.get("status") == "active"]
    if decisions:
        lines = []
        for d in decisions[:10]:
            lines.append(f"- {d.get('title', d['_slug'])}: {d.get('decided_by', '?')} ({d.get('date', '?')})")
        add_section("Active Decisions", "\n".join(lines), budgets[0])

    # 2. Open gaps (papers with open questions)
    papers = [e for e in entities if e["_type"] == "papers"]
    if papers:
        lines = []
        for p in sorted(papers, key=lambda x: x.get("importance", 3), reverse=True)[:10]:
            imp = "*" * p.get("importance", 3)
            lines.append(f"- [{imp}] {p.get('title', p['_slug'])} — {p.get('tldr', '')[:80]}")
        add_section("Key Papers", "\n".join(lines), budgets[3])

    # 3. Failed experiments (anti-repetition memory)
    failed = [e for e in entities if e.get("status") in ("failed", "abandoned", "superseded")]
    if failed:
        lines = []
        for f in failed[:5]:
            reason = f.get("failure_reason", "")[:60]
            lines.append(f"- {f.get('title', f['_slug'])}: {reason}")
        add_section("Failed / Superseded (anti-repetition)", "\n".join(lines), budgets[2])

    # 4. Active projects
    projects = [e for e in entities if e["_type"] == "projects" and e.get("status") == "active"]
    if projects:
        lines = []
        for p in projects:
            lines.append(f"- {p.get('title', p['_slug'])} (PI: {p.get('pi', '?')})")
        add_section("Active Projects", "\n".join(lines), budgets[4])

    # 5. Recent edges
    edges = _load_edges()
    if edges:
        lines = []
        for e in edges[-25:]:
            lines.append(f"- {e['from']} →{e['type']}→ {e['to']}")
        add_section("Recent Graph Edges", "\n".join(lines), budgets[5])

    # 6. Stale entities (not updated in 30 days)
    stale = []
    for e in entities:
        updated = e.get("date_updated") or e.get("date_added", "")
        if updated:
            try:
                d = datetime.strptime(str(updated), "%Y-%m-%d")
                if (now - d.replace(tzinfo=timezone(timedelta(hours=8)))).days > 30:
                    stale.append(e)
            except (ValueError, TypeError):
                pass
    if stale:
        lines = [f"- {e.get('title', e['_slug'])} ({e['_type']}) — last: {e.get('date_updated', e.get('date_added', '?'))}" for e in stale[:10]]
        add_section("Stale Entities (>30 days)", "\n".join(lines), budgets[6])

    return "\n\n".join(sections) if sections else "No wiki content available."


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def get_stats() -> dict:
    """Print wiki page/edge counts."""
    entities = scan_entities()
    by_type: Dict[str, int] = {}
    for e in entities:
        by_type[e["_type"]] = by_type.get(e["_type"], 0) + 1

    edges = _load_edges()
    edge_types: Dict[str, int] = {}
    for e in edges:
        t = e.get("type", "unknown")
        edge_types[t] = edge_types.get(t, 0) + 1

    return {
        "total_entities": len(entities),
        "by_type": by_type,
        "total_edges": len(edges),
        "edge_types": edge_types,
    }


# ---------------------------------------------------------------------------
# Memory index rebuild
# ---------------------------------------------------------------------------

def rebuild_memory_index() -> dict:
    entities = scan_entities()
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    by_type: Dict[str, List[dict]] = {}
    for ent in entities:
        etype = ent.get("_type", "unknown")
        by_type.setdefault(etype, []).append(ent)

    type_names = {
        "projects": "Projects", "papers": "Papers", "methods": "Methods",
        "datasets": "Datasets", "code": "Code", "decisions": "Decisions",
        "configs": "Configs", "people": "People", "meetings": "Meetings",
    }

    lines = [
        "---", "name: wiki-index",
        f"description: Index of the Atlas memory graph — {len(entities)} entities across {len(by_type)} types. Use atlas search for details.",
        "metadata:", "  type: reference", "---", "",
        "## Wiki Overview", "",
        f"Location: `{WIKI_ROOT}`",
        f"Last sync: {now}", f"Total entities: {len(entities)}", "",
    ]

    for etype in CONFIG.get("entity_types", {}):
        items = by_type.get(etype, [])
        display = type_names.get(etype, etype.title())
        lines.append(f"## {display} ({len(items)})")
        if items:
            for item in sorted(items, key=lambda x: x.get("title") or x.get("name") or ""):
                title = item.get("title") or item.get("name") or item.get("_slug", "")
                slug = item.get("_slug", "")
                extras = []
                if item.get("status"):
                    extras.append(f"status:{item['status']}")
                if item.get("year"):
                    extras.append(f"year:{item['year']}")
                if item.get("importance"):
                    extras.append(f"importance:{item['importance']}")
                if item.get("tldr"):
                    extras.append(item["tldr"][:60])
                extra_str = ", ".join(extras)
                lines.append(f"- [[{slug}]] — {title}" + (f" ({extra_str})" if extra_str else ""))
        else:
            lines.append("- _(empty)_")
        lines.append("")

    index_content = "\n".join(lines) + "\n"
    MEMORY_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(MEMORY_INDEX_PATH, index_content)

    return {"ok": True, "total_entities": len(entities), "by_type": {k: len(v) for k, v in by_type.items()}}


# ---------------------------------------------------------------------------
# List entities
# ---------------------------------------------------------------------------

def list_entities(entity_type: Optional[str] = None, limit: int = 50) -> list:
    entities = scan_entities(entity_type)
    results = []
    for ent in entities[:limit]:
        results.append({
            "slug": ent.get("_slug"), "type": ent.get("_type"),
            "title": ent.get("title") or ent.get("name"),
            "status": ent.get("status"), "file": ent.get("_file"),
        })
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Atlas deterministic memory writer")
    sub = parser.add_subparsers(dest="command")

    # write
    p_write = sub.add_parser("write", help="Create a new entity")
    p_write.add_argument("--type", required=True)
    p_write.add_argument("--slug", required=True)
    p_write.add_argument("--frontmatter", required=True, help="JSON string")
    p_write.add_argument("--body", default="", help="Markdown body content")

    # update
    p_update = sub.add_parser("update", help="Update entity frontmatter")
    p_update.add_argument("--slug", required=True)
    p_update.add_argument("--set", required=True, help="JSON string of fields to update")

    # link
    p_link = sub.add_parser("link", help="Add a bidirectional link")
    p_link.add_argument("--from-slug", required=True)
    p_link.add_argument("--to-slug", required=True)
    p_link.add_argument("--field", required=True)

    # unlink
    p_unlink = sub.add_parser("unlink", help="Remove a link")
    p_unlink.add_argument("--from-slug", required=True)
    p_unlink.add_argument("--to-slug", required=True)
    p_unlink.add_argument("--field", required=True)

    # add-edge
    p_edge = sub.add_parser("add-edge", help="Add a semantic graph edge")
    p_edge.add_argument("--from-id", required=True)
    p_edge.add_argument("--to-id", required=True)
    p_edge.add_argument("--type", required=True)
    p_edge.add_argument("--evidence", default="")
    p_edge.add_argument("--confidence", default=None)

    # neighbors
    p_nb = sub.add_parser("neighbors", help="BFS graph traversal")
    p_nb.add_argument("--node", required=True)
    p_nb.add_argument("--depth", type=int, default=1)

    # resolve
    p_resolve = sub.add_parser("resolve", help="Fuzzy match an entity")
    p_resolve.add_argument("--query", required=True)
    p_resolve.add_argument("--type", default=None)

    # check-dup
    p_dup = sub.add_parser("check-dup", help="Check for duplicate entity")
    p_dup.add_argument("--title", required=True)
    p_dup.add_argument("--type", required=True)

    # lint
    sub.add_parser("lint", help="Run structural linter")

    # context
    p_ctx = sub.add_parser("context", help="Compile context summary")
    p_ctx.add_argument("--purpose", default="general", choices=["general", "research", "writing"])
    p_ctx.add_argument("--max-chars", type=int, default=8000)

    # rebuild-index
    sub.add_parser("rebuild-index", help="Rebuild memory index")

    # list
    p_list = sub.add_parser("list", help="List entities")
    p_list.add_argument("--type", default=None)
    p_list.add_argument("--limit", type=int, default=50)

    # stats
    sub.add_parser("stats", help="Print wiki statistics")

    args = parser.parse_args()

    if args.command == "write":
        fm = json.loads(args.frontmatter)
        result = write_entity(args.type, args.slug, fm, args.body)
    elif args.command == "update":
        updates = json.loads(args.set)
        result = update_entity(args.slug, updates)
    elif args.command == "link":
        result = add_link(args.from_slug, args.to_slug, args.field)
    elif args.command == "unlink":
        result = remove_link(args.from_slug, args.to_slug, args.field)
    elif args.command == "add-edge":
        result = add_edge(args.from_id, args.to_id, args.type, args.evidence, args.confidence)
    elif args.command == "neighbors":
        result = get_neighbors(args.node, args.depth)
    elif args.command == "resolve":
        result = resolve_entity(args.query, args.type)
    elif args.command == "check-dup":
        result = check_duplicate(args.title, args.type)
    elif args.command == "lint":
        result = lint_wiki()
    elif args.command == "context":
        result = compile_context(args.purpose, args.max_chars)
        print(result)
        sys.exit(0)
    elif args.command == "rebuild-index":
        result = rebuild_memory_index()
    elif args.command == "list":
        result = list_entities(args.type, args.limit)
    elif args.command == "stats":
        result = get_stats()
    else:
        parser.print_help()
        sys.exit(1)

    if isinstance(result, (dict, list)):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif isinstance(result, str):
        print(result)


if __name__ == "__main__":
    main()
