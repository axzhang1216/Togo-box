#!/usr/bin/env python3
"""
wiki_lint.py — Structural linter for the Atlas memory graph.

Inspired by omegaWiki's lint.py. Checks:
  1. Missing required fields
  2. Broken wikilinks
  3. Orphan pages (no incoming links)
  4. Invalid enum values
  5. Link field targets exist
  6. Xref asymmetry (forward→reverse link integrity)
  7. Graph edge validity
  8. Content quality suggestions

Usage:
  python wiki_lint.py [--json] [--fix]
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

# Add parent to path for wiki_writer imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_writer import (
    CONFIG, XREF, WIKI_ROOT, EDGES_PATH,
    parse_frontmatter, get_entity_dir, get_tag_for_type,
    validate_entity, atomic_write, _load_edges, _edge_key,
    scan_entities, find_entity_file,
)


# ---------------------------------------------------------------------------
# Issue class
# ---------------------------------------------------------------------------

class LintIssue:
    LEVEL_EMOJI = {"red": "[RED]", "yellow": "[WARN]", "blue": "[INFO]"}

    def __init__(self, level: str, category: str, file: str, message: str,
                 fixable: bool = False, suggestion: str = ""):
        self.level = level
        self.category = category
        self.file = file
        self.message = message
        self.fixable = fixable
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "level": self.level, "emoji": self.LEVEL_EMOJI.get(self.level, ""),
            "category": self.category, "file": self.file,
            "message": self.message, "fixable": self.fixable,
        }

    def __str__(self) -> str:
        emoji = self.LEVEL_EMOJI.get(self.level, "")
        loc = Path(self.file).name if self.file else "(global)"
        return f"{emoji} [{self.category}] {loc}: {self.message}"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_missing_fields(entities: List[Dict[str, Any]]) -> List[LintIssue]:
    """Check required fields per entity type."""
    issues = []
    for ent in entities:
        etype = ent["_type"]
        type_info = CONFIG.get("entity_types", {}).get(etype, {})
        for field in type_info.get("key_fields", []):
            val = ent.get(field)
            if val is None or val == "" or val == []:
                issues.append(LintIssue("yellow", "missing-field", ent["_file"],
                                        f"Missing field: {field}", fixable=True))
    return issues


def check_broken_links(entities: List[Dict[str, Any]], all_slugs: Set[str]) -> Tuple[List[LintIssue], Dict[str, int]]:
    """Check for broken [[wikilinks]] in body and frontmatter. Returns issues + incoming count."""
    issues = []
    incoming: Dict[str, int] = {s: 0 for s in all_slugs}

    for ent in entities:
        body = ent.get("_body", "")

        # Body wikilinks
        for match in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", body):
            target = match.group(1).strip()
            if target not in all_slugs:
                issues.append(LintIssue("yellow", "broken-link", ent["_file"],
                                        f"Broken wikilink: [[{target}]]"))
            else:
                incoming[target] = incoming.get(target, 0) + 1

        # Frontmatter link fields
        for field in ["project", "related_papers", "uses_methods", "uses_datasets",
                       "source_papers", "supersedes", "related_configs", "attendees",
                       "collaborators", "related_methods", "related_code"]:
            val = ent.get(field)
            if isinstance(val, str) and "[[" in val:
                for m in re.finditer(r"\[\[([^\]|]+)", val):
                    target = m.group(1).strip()
                    if target not in all_slugs:
                        issues.append(LintIssue("yellow", "broken-link", ent["_file"],
                                                f"Broken frontmatter link: {field} -> [[{target}]]"))
                    else:
                        incoming[target] = incoming.get(target, 0) + 1
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and "[[" in item:
                        target = item.strip("[]").split("|")[0].strip()
                        if target not in all_slugs:
                            issues.append(LintIssue("yellow", "broken-link", ent["_file"],
                                                    f"Broken frontmatter link: {field} -> [[{target}]]"))
                        else:
                            incoming[target] = incoming.get(target, 0) + 1

    return issues, incoming


def check_orphan_pages(entities: List[Dict[str, Any]], incoming: Dict[str, int]) -> List[LintIssue]:
    """Pages with zero incoming links."""
    issues = []
    for ent in entities:
        slug = ent["_slug"]
        if incoming.get(slug, 0) == 0:
            issues.append(LintIssue("blue", "orphan", ent["_file"],
                                    f"Orphan page: {slug} (no incoming links)"))
    return issues


def check_field_values(entities: List[Dict[str, Any]]) -> List[LintIssue]:
    """Validate enum fields and ranges."""
    issues = []
    for ent in entities:
        etype = ent["_type"]
        type_info = CONFIG.get("entity_types", {}).get(etype, {})

        # Check enum fields (e.g., status_values, type_values)
        for key, valid_values in type_info.items():
            if key.endswith("_values") and isinstance(valid_values, list):
                base_field = key.replace("_values", "")
                val = ent.get(base_field)
                if val is not None and val not in valid_values:
                    issues.append(LintIssue("red", "invalid-value", ent["_file"],
                                            f"Invalid {base_field}: '{val}' (must be: {', '.join(str(v) for v in valid_values)})"))

        # Paper importance range
        if etype == "papers" and "importance" in ent:
            imp = ent["importance"]
            if imp is not None and (not isinstance(imp, int) or imp < 1 or imp > 5):
                issues.append(LintIssue("red", "invalid-value", ent["_file"],
                                        f"importance must be 1-5, got {imp}"))

    return issues


def check_xref_asymmetry(entities: List[Dict[str, Any]]) -> List[LintIssue]:
    """Check that every forward link has a corresponding reverse link per xref rules."""
    issues = []
    rules = XREF.get("rules", [])
    terminal = set(XREF.get("terminal_targets", []))

    # Build slug→entity lookup
    slug_map: Dict[str, Dict[str, Any]] = {}
    for ent in entities:
        slug_map[ent["_slug"]] = ent

    for rule in rules:
        fwd = rule["forward"]
        rev = rule["reverse"]
        fwd_kind = fwd["kind"]
        fwd_field = fwd["field"]
        target_kind = fwd["target"]
        rev_kind = rev["kind"]

        for ent in entities:
            # Match forward kind
            if fwd_kind != "*" and ent["_type"] != fwd_kind:
                continue

            # Get link values from frontmatter
            link_val = ent.get(fwd_field)
            if link_val is None or link_val == "" or link_val == []:
                continue

            # Extract target slugs
            target_slugs = []
            if isinstance(link_val, str) and "[[" in link_val:
                for m in re.finditer(r"\[\[([^\]|]+)", link_val):
                    target_slugs.append(m.group(1).strip())
            elif isinstance(link_val, list):
                for item in link_val:
                    if isinstance(item, str) and "[[" in item:
                        target_slugs.append(item.strip("[]").split("|")[0].strip())

            for target_slug in target_slugs:
                target_ent = slug_map.get(target_slug)
                if not target_ent:
                    continue  # broken link (caught by check_broken_links)

                if target_ent["_type"] in terminal:
                    continue  # terminal, no reverse needed

                if target_ent["_type"] != rev_kind:
                    continue  # type mismatch

                # Check reverse exists
                rev_field = rev.get("field")
                rev_section = rev.get("body_section")

                reverse_found = False

                if rev_field:
                    rev_val = target_ent.get(rev_field)
                    if isinstance(rev_val, list):
                        reverse_found = any(
                            isinstance(r, str) and ent["_slug"] in r for r in rev_val
                        )
                    elif isinstance(rev_val, str):
                        reverse_found = ent["_slug"] in rev_val

                if not reverse_found and rev_section:
                    reverse_found = rev_section in target_ent.get("_body", "") and ent["_slug"] in target_ent.get("_body", "")

                if not reverse_found:
                    issues.append(LintIssue("yellow", "xref-asymmetry", ent["_file"],
                                            f"Forward link {fwd_field} -> [[{target_slug}]] missing reverse in {rev_kind}"))
    return issues


def check_graph_edges() -> List[LintIssue]:
    """Validate edges.jsonl entries."""
    issues = []
    edges = _load_edges()
    seen_keys = set()

    for i, edge in enumerate(edges):
        if not edge.get("from") or not edge.get("to") or not edge.get("type"):
            issues.append(LintIssue("red", "graph-edge", str(EDGES_PATH),
                                    f"Edge line {i+1}: missing required fields"))
            continue

        # Dedup check
        key = _edge_key(edge)
        if key in seen_keys:
            issues.append(LintIssue("yellow", "graph-edge", str(EDGES_PATH),
                                    f"Duplicate edge: {key}"))
        seen_keys.add(key)

        # Self-edge
        if edge["from"] == edge["to"]:
            issues.append(LintIssue("yellow", "graph-edge", str(EDGES_PATH),
                                    f"Self-edge: {edge['from']}"))

    return issues


def check_content_quality(entities: List[Dict[str, Any]]) -> List[LintIssue]:
    """Blue-level content suggestions."""
    issues = []
    for ent in entities:
        etype = ent["_type"]

        # Papers with importance >= 4 but no tldr
        if etype == "papers" and ent.get("importance", 0) >= 4 and not ent.get("tldr"):
            issues.append(LintIssue("blue", "content", ent["_file"],
                                    "High-importance paper missing tldr"))

        # Empty body sections
        body = ent.get("_body", "")
        if not body.strip():
            issues.append(LintIssue("blue", "content", ent["_file"],
                                    "Empty body content"))

    return issues


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------

def fix_issues(entities: List[Dict[str, Any]], issues: List[LintIssue]) -> int:
    """Attempt to fix fixable issues. Returns count of fixes applied."""
    fixed = 0
    for issue in issues:
        if not issue.fixable:
            continue
        if issue.category == "missing-field":
            # Find the entity file and add the default value
            fpath = Path(issue.file)
            if not fpath.exists():
                continue
            content = fpath.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(content)
            # Extract field name from message
            field = issue.message.split("Missing field: ")[-1].strip()
            if field not in fm:
                # Find default from config
                for ent in entities:
                    if ent.get("_file") == str(fpath):
                        etype = ent["_type"]
                        break
                else:
                    continue
                tag = get_tag_for_type(etype)
                defaults = {"tags": [tag], "slug": fpath.stem, "date_added": "2026-01-01"}
                fm[field] = defaults.get(field, "")
                atomic_write(fpath, f"---\n{yaml.dump(fm, allow_unicode=True, sort_keys=False)}---\n\n{body}\n")
                fixed += 1
    return fixed


# ---------------------------------------------------------------------------
# Main lint
# ---------------------------------------------------------------------------

def lint(use_json: bool = False, auto_fix: bool = False) -> int:
    """Run all lint checks. Returns exit code (0=clean, 1=issues, 2=errors)."""
    entities = scan_entities()
    all_slugs = {e["_slug"] for e in entities}

    issues: List[LintIssue] = []
    issues.extend(check_missing_fields(entities))
    broken_link_issues, incoming = check_broken_links(entities, all_slugs)
    issues.extend(broken_link_issues)
    issues.extend(check_orphan_pages(entities, incoming))
    issues.extend(check_field_values(entities))
    issues.extend(check_xref_asymmetry(entities))
    issues.extend(check_graph_edges())
    issues.extend(check_content_quality(entities))

    if auto_fix:
        fixes = fix_entities(entities, issues)
        if fixes > 0:
            print(f"Fixed {fixes} issues")

    if use_json:
        print(json.dumps([i.to_dict() for i in issues], ensure_ascii=False, indent=2))
    else:
        red = sum(1 for i in issues if i.level == "red")
        yellow = sum(1 for i in issues if i.level == "yellow")
        blue = sum(1 for i in issues if i.level == "blue")

        if not issues:
            print("All checks passed!")
        else:
            print(f"\nLint results: {red} red | {yellow} yellow | {blue} blue\n")
            for issue in sorted(issues, key=lambda i: ("red", "yellow", "blue").index(i.level)):
                print(str(issue))

    return 2 if any(i.level == "red" for i in issues) else (1 if issues else 0)


def fix_entities(entities, issues):
    """Apply auto-fixes."""
    return fix_issues(entities, issues)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Wiki structural linter")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--fix", action="store_true", help="Auto-fix fixable issues")
    args = parser.parse_args()

    exit_code = lint(use_json=args.json, auto_fix=args.fix)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
