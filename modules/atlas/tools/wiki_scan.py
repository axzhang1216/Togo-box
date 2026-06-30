#!/usr/bin/env python3
"""
wiki_scan.py — Scan vault directories and pre-classify notes for wiki adoption.

Phase 1 of /wiki-adopt: scan + classify + generate migration plan.

Usage:
  python wiki_scan.py                          # Scan entire vault
  python wiki_scan.py --dir "Research Projects" # Scan specific directory
  python wiki_scan.py --type paper              # Only report papers
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_writer import CONFIG, WIKI_ROOT, normalize_text, slugify, scan_entities as wiki_scan

VAULT_ROOT = WIKI_ROOT.parent

# Skip these directories
SKIP_DIRS = {".obsidian", ".trash", "attachments", "Wiki", ".claude", "bin", "Excalidraw"}
SKIP_SUFFIXES = {".canvas", ".loom", ".tmp", ".jpg", ".png", ".pdf", ".base"}


def parse_frontmatter(content: str) -> dict:
    """Quick YAML frontmatter extraction."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                return {}
    return {}


def _infer_kind(entity_type: str, filepath: Path, content: str, fm: dict, tags_str: str) -> str:
    """Infer the 'kind' sub-type for an entity."""
    text = content.lower()
    rel = str(filepath.relative_to(VAULT_ROOT)).lower()

    if entity_type == "thing":
        if "#reading" in text or "abstract" in text or "arxiv" in text:
            return "paper"
        if "```python" in text or "```bash" in text or "```fortran" in text or "github" in text:
            return "code"
        if "namelist" in text or ".rc" in text or "参数" in text or "#config" in tags_str:
            return "config"
        if "reanalysis" in text or "satellite" in text or "变量" in text or "分辨率" in text:
            return "dataset"
        if "algorithm" in text or "procedure" in text or "步骤" in text:
            return "method"
        if "research project" in rel or any(p in rel for p in ["research projects", "proj"]):
            return "project"
        if "geos-chem" in text or "wrf" in text or "hemo" in text:
            return "model"
        return "other"

    if entity_type == "event":
        if "组会" in text or "meeting" in tags_str or "attendees" in text:
            return "meeting"
        if "debug" in text or "bug" in text:
            return "debug"
        if "conference" in text or "seminar" in text:
            return "conference"
        if "experiment" in text or "实验" in text:
            return "experiment"
        return "discussion"

    if entity_type == "statement":
        if "决定" in text or "chose" in text or "选了" in text or "trade-off" in text:
            return "decision"
        if "constraint" in text or "约束" in text or "不能" in text or "必须" in text:
            return "constraint"
        if "hypothesis" in text or "假设" in text:
            return "hypothesis"
        if "finding" in text or "发现" in text or "结论" in text:
            return "finding"
        return "other"

    if entity_type == "actor":
        if "team" in text or "课题组" in text or "lab" in text:
            return "team"
        if "university" in text or "大学" in text or "institute" in text:
            return "organization"
        return "person"

    return "other"


def classify_note(filepath: Path, content: str, fm: dict) -> Optional[str]:
    """Classify a note into a wiki entity type based on 5-type minimal ontology.

    Types: thing, event, statement, actor, note
    Returns (entity_type, kind) tuple.
    """
    text = content.lower()
    tags = fm.get("tags", []) or []
    if isinstance(tags, str):
        tags = [tags]
    tags = [t for t in tags if t is not None]
    tags_str = " ".join(str(t) for t in tags).lower()

    # ── ACTOR ──
    actor_signals = [
        "affiliation" in text,
        "research area" in text and "person" in text,
        "## 简介" in text and ("教授" in text or "导师" in text or "学生" in text),
        "#person" in tags_str or "#actor" in tags_str,
    ]
    if sum(actor_signals) >= 1:
        return "actor"

    # ── EVENT ──
    event_signals = [
        "attendees" in text or "参会" in text,
        "## agenda" in text or "## 议题" in text,
        "## action items" in text or "## 待办" in text,
        "组会" in text or "meeting" in tags_str,
        "conference" in text and ("notes" in text or "summary" in text),
        "## background" in text and ("## procedure" in text or "## 经过" in text),
        "debug" in text and ("## log" in text or "## 记录" in text),
        "#meeting" in tags_str or "#event" in tags_str,
    ]
    if sum(event_signals) >= 2:
        return "event"
    if sum(event_signals) >= 1 and ("meeting" in text or "组会" in text or "会议" in text):
        return "event"

    # ── STATEMENT ──
    statement_signals = [
        "## rationale" in text or "## 理由" in text,
        "chosen over" in text or "选了" in text or "决定" in text,
        "trade-off" in text or "tradeoff" in text,
        "## constraint" in text or "## 约束" in text,
        "## conclusion" in text or "## 结论" in text,
        "## finding" in text or "## 发现" in text,
        "## hypothesis" in text or "## 假设" in text,
        "rule" in tags_str or "#decision" in tags_str,
        "注意" in text and ("不能" in text or "必须" in text or "不要" in text),
    ]
    if sum(statement_signals) >= 1:
        return "statement"

    # ── THING ──
    thing_signals = [
        # Code/tool
        "```python" in text or "```bash" in text or "```fortran" in text,
        "git clone" in text or "pip install" in text,
        "github.com" in text or "gitlab" in text,
        "## installation" in text or "## 安装" in text,
        "#code" in tags_str or "#tool" in tags_str,
        # Config
        "namelist" in text or ".rc" in text,
        "## parameters" in text or "## 参数" in text,
        "#config" in tags_str,
        # Dataset
        "## variables" in text or "## 变量" in text,
        "## resolution" in text or "## 分辨率" in text,
        "reanalysis" in text or "satellite" in text,
        "#dataset" in tags_str,
        # Method
        "## procedure" in text or "## 步骤" in text,
        "algorithm" in text and ("step" in text or "input" in text),
        "#method" in tags_str,
        # Paper (treated as thing with kind=paper)
        "#reading" in text,
        "## abstract" in text,
        "@article" in text or "@inproceedings" in text,
        "arxiv.org" in text or "doi.org" in text,
        "doi:" in text,
        # Model/tool
        "GEOS-Chem" in text or "WRF" in text or "HEMCO" in text,
    ]
    if sum(thing_signals) >= 1:
        return "thing"

    return None  # Falls through to note


def extract_project_from_path(filepath: Path) -> Optional[str]:
    """Try to extract project name from file path."""
    parts = filepath.relative_to(VAULT_ROOT).parts
    if parts[0] == "Research Projects" and len(parts) > 1:
        return parts[1]  # e.g., "GEOS-Chem"
    return None


def scan_vault(scan_dir: Optional[str] = None, filter_type: Optional[str] = None) -> dict:
    """Scan vault and generate migration plan."""
    # Get existing wiki slugs for dedup
    existing = {e["_slug"] for e in wiki_scan()}

    # Determine scan root
    if scan_dir:
        scan_root = VAULT_ROOT / scan_dir
    else:
        scan_root = VAULT_ROOT

    results = {"plan": [], "skipped": [], "existing": [], "errors": []}

    for root, dirs, files in os.walk(scan_root):
        # Skip excluded directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for fname in sorted(files):
            if not fname.endswith(".md"):
                continue
            if any(fname.endswith(s) for s in SKIP_SUFFIXES):
                continue

            filepath = Path(root) / fname
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception as e:
                results["errors"].append({"file": str(filepath), "error": str(e)})
                continue

            if len(content.strip()) < 50:
                results["skipped"].append({"file": str(filepath), "reason": "too short"})
                continue

            # Parse frontmatter
            fm = parse_frontmatter(content)

            # Generate slug
            slug = filepath.stem
            slug = slugify(slug)
            # Add year prefix if filename starts with year
            year_match = re.match(r"(\d{4})_", fname)
            if year_match:
                slug = fname.replace(".md", "").replace("_", "-").lower()
                slug = re.sub(r"[^a-z0-9-]", "", slug)

            # Check if already in wiki
            if slug in existing:
                results["existing"].append({"file": str(filepath), "slug": slug})
                continue

            # Classify
            entity_type = classify_note(filepath, content, fm)
            if filter_type and entity_type != filter_type:
                continue

            if entity_type is None:
                results["skipped"].append({
                    "file": str(filepath),
                    "reason": "unclassified",
                    "title": fm.get("title", filepath.stem),
                })
                continue

            # Extract fields
            title = fm.get("title") or fname.replace(".md", "").replace("_", " ")
            project = extract_project_from_path(filepath)
            tags = fm.get("tags", []) or []
            if isinstance(tags, str):
                tags = [tags]
            tags = [t for t in tags if t is not None]
            tags_str = " ".join(str(t) for t in tags).lower()

            # Build frontmatter for wiki entity
            wiki_fm = {"title": title, "slug": slug}
            if tags:
                wiki_fm["tags"] = tags
            if project:
                wiki_fm["project"] = f"[[{slugify(project)}]]"

            # Infer kind based on content and path
            kind = _infer_kind(entity_type, filepath, content, fm, tags_str)

            # Type-specific fields
            if entity_type == "thing":
                wiki_fm["kind"] = kind
                wiki_fm["description"] = fm.get("description", "")[:200]
            elif entity_type == "event":
                wiki_fm["kind"] = kind
                wiki_fm["date"] = fm.get("date", "")
                wiki_fm["actors"] = fm.get("actors", [])
                wiki_fm["outcome"] = fm.get("outcome", "")
            elif entity_type == "statement":
                wiki_fm["kind"] = kind
                wiki_fm["status"] = fm.get("status", "active")
                wiki_fm["confidence"] = fm.get("confidence", "medium")
                wiki_fm["source"] = []
            elif entity_type == "actor":
                wiki_fm["kind"] = kind
                wiki_fm["name"] = fm.get("name", title)
                wiki_fm["affiliation"] = fm.get("affiliation", "")
                wiki_fm["role"] = fm.get("role", "collaborator")

            results["plan"].append({
                "source": str(filepath.relative_to(VAULT_ROOT)),
                "type": entity_type,
                "kind": kind,
                "slug": slug,
                "title": title,
                "project": project,
                "tags": tags[:5],  # first 5 tags
                "wiki_fm": wiki_fm,
                "body_preview": content[:200].replace("\n", " "),
            })

    # Sort plan by type then title
    results["plan"].sort(key=lambda x: (x["type"], x["title"]))

    return results


def print_plan(results: dict) -> None:
    """Print a human-readable migration plan."""
    plan = results["plan"]
    skipped = results["skipped"]
    existing = results["existing"]
    errors = results["errors"]

    # Summary by type
    by_type: dict = {}
    for item in plan:
        by_type[item["type"]] = by_type.get(item["type"], 0) + 1

    print(f"\n=== Wiki Adoption Plan ===\n")
    print(f"Entities to create: {len(plan)}")
    for t, c in sorted(by_type.items()):
        print(f"  {t}: {c}")
    print(f"Skipped (unclassifiable): {len(skipped)}")
    print(f"Already in wiki: {len(existing)}")
    print(f"Errors: {len(errors)}")

    # Detail table
    print(f"\n{'#':>3} | {'Type':<12} | {'Slug':<30} | {'Title':<40} | Source")
    print("-" * 120)
    for i, item in enumerate(plan, 1):
        title_short = item["title"][:38] + ".." if len(item["title"]) > 40 else item["title"]
        slug_short = item["slug"][:28] + ".." if len(item["slug"]) > 30 else item["slug"]
        print(f"{i:>3} | {item['type']:<12} | {slug_short:<30} | {title_short:<40} | {item['source']}")

    if skipped:
        print(f"\n--- Skipped ({len(skipped)}) ---")
        for s in skipped[:20]:
            print(f"  {s['reason']:<15} {s['file']}")


def main():
    parser = argparse.ArgumentParser(description="Scan vault for wiki adoption")
    parser.add_argument("--dir", default=None, help="Subdirectory to scan (relative to vault)")
    parser.add_argument("--type", default=None, help="Filter to specific entity type")
    parser.add_argument("--json", action="store_true", help="Output JSON plan")
    parser.add_argument("--output", default=None, help="Save JSON plan to file")
    args = parser.parse_args()

    results = scan_vault(args.dir, args.type)

    if args.json:
        sys.stdout.reconfigure(encoding='utf-8')
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"Plan saved to {args.output}")
        print_plan(results)
    else:
        print_plan(results)


if __name__ == "__main__":
    main()
