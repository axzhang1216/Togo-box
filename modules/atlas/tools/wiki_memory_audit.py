#!/usr/bin/env python3
"""Audit likely low-quality Wiki memory artifacts without deleting anything."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_writer import WIKI_ROOT, parse_frontmatter, scan_entities  # noqa: E402


IMAGE_RE = re.compile(r"\.(png|jpg|jpeg|gif|webp|svg)$", re.I)
RANDOMISH_RE = re.compile(r"^[a-z0-9-]{40,}$", re.I)
SHORT_TOKEN_RE = re.compile(r"^[a-z]{1,3}$", re.I)


def reasons_for_entity(entity: dict) -> list[str]:
    title = str(entity.get("title") or entity.get("name") or entity.get("_slug") or "")
    slug = str(entity.get("_slug") or "")
    reasons = []
    if IMAGE_RE.search(title) or IMAGE_RE.search(slug):
        reasons.append("image-or-attachment-entity")
    if "/" in title or "\\" in title:
        reasons.append("path-like-title")
    if RANDOMISH_RE.match(slug):
        reasons.append("random-looking-long-slug")
    if SHORT_TOKEN_RE.match(title):
        reasons.append("short-generic-token")
    if title.lower() in {"cpu", "home", "data", "scratch", "url", "pdf", "png", "nc"}:
        reasons.append("generic-technical-word")
    mentioned = entity.get("mentioned_in", [])
    if not mentioned:
        reasons.append("no-mentioned-in")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit likely junk memories/entities")
    parser.add_argument("--output", default=None, help="Write JSON report path")
    args = parser.parse_args()

    findings = []
    for entity in scan_entities():
        reasons = reasons_for_entity(entity)
        if reasons:
            findings.append({
                "slug": entity.get("_slug"),
                "type": entity.get("_type"),
                "title": entity.get("title") or entity.get("name"),
                "file": entity.get("_file"),
                "reasons": reasons,
            })

    report = {
        "wiki_root": str(WIKI_ROOT),
        "finding_count": len(findings),
        "findings": findings,
        "note": "Non-destructive audit only. Review before deleting, merging, or quarantining.",
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
