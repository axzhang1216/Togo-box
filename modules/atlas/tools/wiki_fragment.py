#!/usr/bin/env python3
"""
wiki_fragment.py — Deterministic fragment writer for Atlas.

Takes a note's fragment plan (JSON) and writes:
1. The note container file (wiki/note/{slug}.md) with fragment markers
2. Creates any new entity files referenced by fragments
3. Builds bidirectional links (mentioned_in on entities, forward links in fragments)
4. Updates the fragment index

Usage:
  python wiki_fragment.py apply --plan fragments.json
  python wiki_fragment.py validate --plan fragments.json
  python wiki_fragment.py plan --source "path/to/note.md"  (generates plan template)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_writer import (
    CONFIG, WIKI_ROOT, atomic_write,
    parse_frontmatter, serialize_frontmatter,
    find_entity_file, slugify, scan_entities, resolve_entity,
    rebuild_memory_index,
)

FRAGMENTS_INDEX = WIKI_ROOT / "fragments.jsonl"
RETRIEVAL_INDEX = WIKI_ROOT / "retrieval_index.jsonl"


# ---------------------------------------------------------------------------
# Fragment plan validation
# ---------------------------------------------------------------------------

VALID_SPEECH_ACTS = {"ASSERT", "DECIDE", "FIND", "DO", "ASK", "REMIND", "CONSTRAIN"}
VALID_MEMORY_ROLES = {
    "fact", "rule", "decision", "finding", "open_question",
    "procedure", "task", "preference", "resource", "context",
}
VALID_ENTITY_TYPES = {"thing", "event", "statement", "actor"}

LEGACY_TYPE_TO_MEMORY_ROLE = {
    "ASSERT": "fact",
    "DECIDE": "decision",
    "FIND": "finding",
    "DO": "procedure",
    "ASK": "open_question",
    "REMIND": "task",
    "CONSTRAIN": "rule",
}


def fragment_memory_role(frag: dict) -> str:
    """Return canonical memory role, accepting legacy speech-act plans."""
    role = frag.get("memory_role")
    if role:
        return role
    legacy_type = frag.get("type")
    if legacy_type in LEGACY_TYPE_TO_MEMORY_ROLE:
        return LEGACY_TYPE_TO_MEMORY_ROLE[legacy_type]
    return ""


def entity_title(ent: dict) -> str:
    """Return the canonical title used for resolution and links."""
    if ent.get("type") == "actor":
        return (ent.get("title") or ent.get("name") or "").strip()
    return (ent.get("title") or "").strip()


def fragment_retrieval(frag: dict) -> dict:
    """Return canonical retrieval object, accepting legacy retrieval_queries."""
    retrieval = frag.get("retrieval")
    if isinstance(retrieval, dict):
        return {
            "semantic_summary": str(retrieval.get("semantic_summary", "")).strip(),
            "direct_queries": retrieval.get("direct_queries", []) or [],
            "indirect_queries": retrieval.get("indirect_queries", []) or [],
            "aliases": retrieval.get("aliases", []) or [],
            "broader_topics": retrieval.get("broader_topics", []) or [],
        }
    return {
        "semantic_summary": str(frag.get("content", "")).strip()[:200],
        "direct_queries": frag.get("retrieval_queries", []) or [],
        "indirect_queries": [],
        "aliases": [],
        "broader_topics": [],
    }


def validate_plan(plan: dict) -> List[str]:
    """Validate a fragment plan. Returns list of errors."""
    errors = []

    if "note" not in plan:
        errors.append("Missing 'note' field (the note container)")
        return errors

    note = plan["note"]
    if "title" not in note:
        errors.append("note.title is required")
    if "slug" not in note:
        errors.append("note.slug is required")
    if "domain" in note and not isinstance(note["domain"], list):
        errors.append("note.domain must be a list when provided")

    fragments = plan.get("fragments", [])
    if not fragments:
        errors.append("No fragments defined")

    for i, frag in enumerate(fragments):
        prefix = f"fragments[{i}]"
        role = fragment_memory_role(frag)
        if not role:
            errors.append(f"{prefix}: missing 'memory_role'")
        elif role not in VALID_MEMORY_ROLES:
            errors.append(f"{prefix}: invalid memory_role '{role}' (must be: {', '.join(sorted(VALID_MEMORY_ROLES))})")
        if "type" in frag and frag["type"] not in VALID_SPEECH_ACTS:
            errors.append(f"{prefix}: invalid legacy type '{frag['type']}' (must be: {', '.join(sorted(VALID_SPEECH_ACTS))})")
        if "content" not in frag or not frag["content"].strip():
            errors.append(f"{prefix}: missing or empty 'content'")
        if "memory_role" in frag:
            if "why_remember" not in frag or not str(frag["why_remember"]).strip():
                errors.append(f"{prefix}: missing or empty 'why_remember'")
            retrieval = fragment_retrieval(frag)
            if not retrieval["semantic_summary"]:
                errors.append(f"{prefix}: missing retrieval.semantic_summary")
            if not retrieval["direct_queries"] and not retrieval["indirect_queries"] and not retrieval["aliases"] and not retrieval["broader_topics"]:
                errors.append(f"{prefix}: missing retrieval cues")
            if "status" in frag and frag["status"] not in {"active", "stale", "deprecated", "superseded", "resolved", "uncertain"}:
                errors.append(f"{prefix}: invalid status '{frag['status']}'")
        # Validate entities
        for j, ent in enumerate(frag.get("entities", [])):
            ep = f"{prefix}.entities[{j}]"
            if "type" not in ent or ent["type"] not in VALID_ENTITY_TYPES:
                errors.append(f"{ep}: invalid or missing entity type")
            if not entity_title(ent):
                errors.append(f"{ep}: missing entity title/name")

    return errors


# ---------------------------------------------------------------------------
# Entity creation / resolution
# ---------------------------------------------------------------------------

def resolve_or_create_entity(ent: dict) -> dict:
    """Resolve existing entity or prepare to create new one.

    Returns: {slug, type, created: bool, file: str}
    """
    title = entity_title(ent)
    ent_type = ent["type"]

    # Try to find existing
    existing = resolve_entity(title, ent_type)
    if existing:
        return {
            "slug": existing["slug"],
            "type": existing["type"],
            "created": False,
            "file": existing["file"],
        }

    # Prepare new entity
    slug = slugify(title)
    # Add type prefix for disambiguation
    candidate_slug = slug
    counter = 1
    while find_entity_file(candidate_slug) is not None:
        candidate_slug = f"{slug}-{counter}"
        counter += 1

    # Build frontmatter
    tag = CONFIG.get("entity_types", {}).get(ent_type, {}).get("tag", f"wiki/{ent_type}")
    fm = {"tags": [tag]}
    for key in ["title", "name", "kind", "description", "status", "confidence",
                 "affiliation", "role", "research_areas", "date", "outcome",
                 "source", "supersedes", "project", "related", "actors"]:
        if key in ent and ent[key] is not None:
            fm[key] = ent[key]
    if ent_type == "actor":
        fm["name"] = ent.get("name") or title
        fm["title"] = ent.get("title") or title
    else:
        fm["title"] = title
    fm["slug"] = candidate_slug
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    fm["date_added"] = now

    return {
        "slug": candidate_slug,
        "type": ent_type,
        "created": True,
        "frontmatter": fm,
    }


# ---------------------------------------------------------------------------
# Apply plan
# ---------------------------------------------------------------------------

def apply_plan(plan: dict) -> dict:
    """Execute a fragment plan: create note + entities + links."""
    # Validate
    errors = validate_plan(plan)
    if errors:
        return {"ok": False, "errors": errors}

    note = plan["note"]
    fragments = plan.get("fragments", [])

    # Step 1: Resolve/create all entities first
    entity_map = {}  # title → resolved info
    entities_created = []
    entities_linked = []

    for frag in fragments:
        for ent in frag.get("entities", []):
            title = entity_title(ent)
            if title not in entity_map:
                resolved = resolve_or_create_entity(ent)
                entity_map[title] = resolved
                if resolved["created"]:
                    entities_created.append(resolved)

    # Step 2: Create entity files
    for ent_info in entities_created:
        ent_type = ent_info["type"]
        slug = ent_info["slug"]
        fm = ent_info["frontmatter"]

        entity_dir = WIKI_ROOT / CONFIG["entity_types"][ent_type]["dir"]
        entity_dir.mkdir(parents=True, exist_ok=True)
        file_path = entity_dir / f"{slug}.md"

        body = f"\n\n> Mentioned in: [[{note['slug']}]]\n"
        content = serialize_frontmatter(fm, body)
        atomic_write(file_path, content)
        ent_info["file"] = str(file_path)

    # Step 3: Write note container with fragment markers
    note_dir = WIKI_ROOT / "note"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_slug = note["slug"]
    note_path = note_dir / f"{note_slug}.md"

    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    note_fm = {
        "title": note["title"],
        "slug": note_slug,
        "tags": ["wiki/note"] + note.get("tags", []),
        "source_path": note.get("source_path", ""),
        "source_type": note.get("source_type", ""),
        "domain": note.get("domain", []),
        "fragment_count": len(fragments),
        "date_added": now,
    }

    body_lines = []
    for i, frag in enumerate(fragments):
        memory_role = fragment_memory_role(frag)
        legacy_type = frag.get("type", "")
        frag_tags = frag.get("tags", [])
        frag_entities = frag.get("entities", [])
        frag_content = frag["content"].strip()
        source_excerpt = str(frag.get("source_excerpt", "")).strip()
        why_remember = str(frag.get("why_remember", "")).strip()
        retrieval = fragment_retrieval(frag)
        relations = frag.get("relations", [])
        status = str(frag.get("status", "")).strip()
        created_at = str(frag.get("created_at", "")).strip()
        last_verified = str(frag.get("last_verified", "")).strip()
        source_evidence = frag.get("source_evidence", [])

        # Build entity links string
        links = []
        for ent in frag_entities:
            title = entity_title(ent)
            resolved = entity_map.get(title, {})
            slug = resolved.get("slug", slugify(title))
            links.append(f"[[{slug}]]")

        # Write fragment marker + content
        tags_str = ",".join(frag_tags) if frag_tags else ""
        links_str = ",".join(links) if links else ""

        marker_parts = [f"memory_role={memory_role}", f"tags=\"{tags_str}\"", f"links=\"{links_str}\""]
        if legacy_type:
            marker_parts.append(f"legacy_type={legacy_type}")
        body_lines.append(f"<!-- fragment: {' '.join(marker_parts)} -->")
        body_lines.append(f"### [{memory_role}] Fragment {i+1}")
        body_lines.append("")
        body_lines.append(frag_content)
        body_lines.append("")
        if source_excerpt:
            body_lines.append(f"> Source: {source_excerpt}")
            body_lines.append("")
        if why_remember:
            body_lines.append(f"Why remember: {why_remember}")
            body_lines.append("")
        if retrieval.get("semantic_summary"):
            body_lines.append(f"Semantic summary: {retrieval['semantic_summary']}")
            body_lines.append("")
        retrieval_groups = []
        for label, values in [
            ("Direct queries", retrieval.get("direct_queries", [])),
            ("Indirect queries", retrieval.get("indirect_queries", [])),
            ("Aliases", retrieval.get("aliases", [])),
            ("Broader topics", retrieval.get("broader_topics", [])),
        ]:
            if values:
                retrieval_groups.append((label, values))
        if retrieval_groups:
            body_lines.append("Retrieval:")
            for label, values in retrieval_groups:
                body_lines.append(f"- {label}:")
                for value in values:
                    body_lines.append(f"  - {value}")
            body_lines.append("")
        if status or created_at or last_verified:
            body_lines.append("Freshness:")
            if status:
                body_lines.append(f"- status: {status}")
            if created_at:
                body_lines.append(f"- created_at: {created_at}")
            if last_verified:
                body_lines.append(f"- last_verified: {last_verified}")
            body_lines.append("")
        if source_evidence:
            body_lines.append("Source evidence:")
            for evidence in source_evidence:
                if isinstance(evidence, dict):
                    locator = evidence.get("locator", "")
                    locator_text = f" ({locator})" if locator else ""
                    body_lines.append(f"- {evidence.get('type', 'other')}: {evidence.get('path', '')}{locator_text} — {evidence.get('detail', '')}")
            body_lines.append("")
        if relations:
            body_lines.append("Relations:")
            for rel in relations:
                if isinstance(rel, dict):
                    body_lines.append(f"- {rel.get('from', '')} --{rel.get('type', 'related_to')}--> {rel.get('to', '')}")
            body_lines.append("")
        body_lines.append("---")
        body_lines.append("")

    # Add entity back-references
    body_lines.append("")
    body_lines.append("## Entities")
    body_lines.append("")
    for title in sorted(entity_map):
        resolved = entity_map.get(title, {})
        slug = resolved.get("slug", slugify(title))
        body_lines.append(f"- [[{slug}]]")

    note_body = "\n".join(body_lines)
    atomic_write(note_path, serialize_frontmatter(note_fm, note_body))

    # Step 4: Update entities' mentioned_in
    for frag in fragments:
        for ent in frag.get("entities", []):
            resolved = entity_map.get(entity_title(ent), {})
            if resolved and "file" in resolved:
                ent_path = Path(resolved["file"])
                if ent_path.exists():
                    content = ent_path.read_text(encoding="utf-8")
                    ent_fm, ent_body = parse_frontmatter(content)
                    mentioned = ent_fm.get("mentioned_in", [])
                    note_link = f"[[{note_slug}]]"
                    if isinstance(mentioned, str):
                        mentioned = [mentioned]
                    if note_link not in mentioned:
                        mentioned.append(note_link)
                    ent_fm["mentioned_in"] = mentioned
                    # Append reverse mention to body if section exists
                    reverse_marker = "## Mentioned in"
                    if reverse_marker not in ent_body:
                        ent_body += f"\n\n{reverse_marker}\n"
                    if note_link not in ent_body:
                        ent_body += f"- {note_link}\n"
                    atomic_write(ent_path, serialize_frontmatter(ent_fm, ent_body))
                    entities_linked.append(resolved["slug"])

    # Step 5: Append to fragments index
    _append_to_index(note, fragments, entity_map)

    # Step 6: Rebuild memory index
    rebuild_memory_index()

    return {
        "ok": True,
        "note": note_slug,
        "fragments": len(fragments),
        "entities_created": len(entities_created),
        "entities_linked": len(set(entities_linked)),
        "note_file": str(note_path),
    }


def _append_to_index(note: dict, fragments: list, entity_map: dict):
    """Upsert fragment and retrieval records for a note."""
    FRAGMENTS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    note_slug = note["slug"]
    note_domain = note.get("domain", [])
    note_source_type = note.get("source_type", "")
    note_source_path = note.get("source_path", "")
    fragment_records = []
    retrieval_records = []
    for i, frag in enumerate(fragments, 1):
        retrieval = fragment_retrieval(frag)
        entities = []
        for ent in frag.get("entities", []):
            resolved = entity_map.get(entity_title(ent), {})
            entities.append({
                "slug": resolved.get("slug", ""),
                "type": resolved.get("type", ""),
                "title": entity_title(ent),
            })
        fragment_id = f"{note_slug}#f{i}"
        record = {
            "id": fragment_id,
            "note": note_slug,
            "fragment": i,
            "memory_role": fragment_memory_role(frag),
            "legacy_type": frag.get("type", ""),
            "content_preview": frag["content"][:160].replace("\n", " "),
            "why_remember": str(frag.get("why_remember", ""))[:240],
            "retrieval": retrieval,
            "retrieval_queries": retrieval.get("direct_queries", []),
            "status": frag.get("status", ""),
            "created_at": frag.get("created_at", ""),
            "last_verified": frag.get("last_verified", ""),
            "domain": frag.get("domain", note_domain),
            "source_type": frag.get("source_type", note_source_type),
            "source_path": note_source_path,
            "source_evidence": frag.get("source_evidence", []),
            "relations": frag.get("relations", []),
            "entities": entities,
        }
        fragment_records.append(record)
        retrieval_records.append({
            "id": fragment_id,
            "note": note_slug,
            "fragment": i,
            "memory_role": record["memory_role"],
            "status": record["status"],
            "last_verified": record["last_verified"],
            "domain": record["domain"],
            "source_type": record["source_type"],
            "source_path": record["source_path"],
            "summary": retrieval.get("semantic_summary") or record["content_preview"],
            "entities": [e["title"] for e in entities if e.get("title")],
            "direct_queries": retrieval.get("direct_queries", []),
            "indirect_queries": retrieval.get("indirect_queries", []),
            "aliases": retrieval.get("aliases", []),
            "broader_topics": retrieval.get("broader_topics", []),
            "source": note_slug,
        })

    _upsert_jsonl_by_note(FRAGMENTS_INDEX, note_slug, fragment_records)
    _upsert_jsonl_by_note(RETRIEVAL_INDEX, note_slug, retrieval_records)


def _upsert_jsonl_by_note(path: Path, note_slug: str, records: list) -> None:
    """Rewrite JSONL while replacing records for one note slug."""
    kept = []
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("note") != note_slug:
                    kept.append(item)
    with open(path, "w", encoding="utf-8") as f:
        for item in kept + records:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Generate plan template
# ---------------------------------------------------------------------------

def plan_template(source_path: str) -> dict:
    """Generate a plan template for a source note."""
    p = Path(source_path)
    slug = slugify(p.stem)
    return {
        "note": {
            "title": p.stem,
            "slug": slug,
            "source_path": source_path,
            "source_type": "markdown",
            "domain": [],
            "tags": [],
        },
        "fragments": [
            {
                "memory_role": "fact|rule|decision|finding|open_question|procedure|task|preference|resource|context",
                "content": " paste fragment text here ",
                "source_excerpt": " supporting source span ",
                "why_remember": " why future agents should retrieve this ",
                "retrieval": {
                    "semantic_summary": "short semantic retrieval summary",
                    "direct_queries": ["likely explicit user query"],
                    "indirect_queries": ["likely indirect user query"],
                    "aliases": ["synonym"],
                    "broader_topics": ["parent topic"],
                },
                "status": "active",
                "created_at": "YYYY-MM-DD",
                "last_verified": "YYYY-MM-DD",
                "source_evidence": [],
                "domain": [],
                "tags": [],
                "entities": [
                    {"type": "thing|event|statement|actor", "title": "Entity Title"}
                ],
                "relations": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Wiki fragment writer")
    sub = parser.add_subparsers(dest="command")

    p_apply = sub.add_parser("apply", help="Execute a fragment plan")
    p_apply.add_argument("--plan", required=True, help="Path to plan JSON file")

    p_validate = sub.add_parser("validate", help="Validate a fragment plan without writing files")
    p_validate.add_argument("--plan", required=True, help="Path to plan JSON file")

    p_plan = sub.add_parser("plan", help="Generate plan template")
    p_plan.add_argument("--source", required=True, help="Source note path")

    args = parser.parse_args()

    if args.command == "apply":
        with open(args.plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
        result = apply_plan(plan)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "validate":
        with open(args.plan, "r", encoding="utf-8") as f:
            plan = json.load(f)
        errors = validate_plan(plan)
        result = {"ok": not errors, "errors": errors}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if errors:
            sys.exit(1)

    elif args.command == "plan":
        result = plan_template(args.source)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
