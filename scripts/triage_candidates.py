#!/usr/bin/env python3
"""
Deterministically triage literature-radar candidates using title/abstract matches.

Input:  output/candidates.json
Output: output/selected.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SKILL_ROOT / "references" / "config.md"
DEFAULT_INPUT = SKILL_ROOT / "output" / "candidates.json"
DEFAULT_OUTPUT = SKILL_ROOT / "output" / "selected.json"

CORE_ATMO_TERMS = [
    "mechanism",
    "rate constant",
    "retrieval",
    "retrieved",
    "emission inventory",
    "source attribution",
    "source apportionment",
    "field campaign",
    "chemical transport model",
    "geos-chem",
    "wrf-chem",
    "cmaq",
    "oxidation",
    "photolysis",
    "halogen",
    "hono",
    "soa",
    "ozone",
    "nox",
]

CORE_ML_TERMS = [
    "neural emulator",
    "surrogate model",
    "physics-informed",
    "foundation model",
    "uncertainty quantification",
    "autonomous science",
    "earth system",
    "geophysical",
    "spatiotemporal",
    "transformer",
    "diffusion model",
    "graph neural network",
    "neural operator",
    "operator learning",
]

PERIPHERAL_TERMS = [
    "dataset",
    "benchmark",
    "intercomparison",
    "review",
    "perspective",
    "commentary",
]


def strip_inline_comment(value: str) -> str:
    if "#" not in value:
        return value.strip()
    return value.split("#", 1)[0].strip()


def unescape_markdown(value: str) -> str:
    return value.replace("\\_", "_").replace("\\[", "[").replace("\\]", "]")


def parse_scalar(value: str) -> Any:
    value = unescape_markdown(strip_inline_comment(value))
    if value == "[]":
        return []
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        return value


def load_config(path: Path) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "max_selected_papers": 10,
        "atmo_keywords": [],
        "ml_keywords": [],
    }

    current_list_key: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("##"):
            current_list_key = None
            continue
        if (stripped.startswith("- ") or stripped.startswith("* ")) and current_list_key:
            item = unescape_markdown(strip_inline_comment(stripped[2:]))
            if item:
                cfg.setdefault(current_list_key, []).append(item)
            continue
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            key = unescape_markdown(key.strip().lower().replace(" ", "_"))
            value = value.strip()
            if value:
                cfg[key] = parse_scalar(value)
                current_list_key = None
            else:
                current_list_key = key
                cfg[current_list_key] = []

    return cfg


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def count_matches(text: str, phrases: list[str]) -> tuple[int, list[str]]:
    hits: list[str] = []
    for phrase in phrases:
        normalized = normalize_text(phrase)
        if normalized and normalized in text:
            hits.append(phrase)
    unique_hits = list(dict.fromkeys(hits))
    return len(unique_hits), unique_hits


def classify_track(text: str, cfg: dict[str, Any]) -> tuple[str, int, list[str]]:
    atmo_terms = list(cfg.get("atmo_keywords", [])) + CORE_ATMO_TERMS
    ml_terms = list(cfg.get("ml_keywords", [])) + CORE_ML_TERMS

    atmo_count, atmo_hits = count_matches(text, atmo_terms)
    ml_count, ml_hits = count_matches(text, ml_terms)
    peripheral_count, peripheral_hits = count_matches(text, PERIPHERAL_TERMS)

    if atmo_count == 0 and ml_count == 0 and peripheral_count == 0:
        return "peripheral", 1, []

    if atmo_count >= ml_count and atmo_count > 0:
        if atmo_count >= 2:
            return "atmo", 3, atmo_hits
        return "peripheral", 2, atmo_hits + peripheral_hits

    if ml_count > 0:
        if ml_count >= 2:
            return "ml", 3, ml_hits
        return "peripheral", 2, ml_hits + peripheral_hits

    return "peripheral", 2, peripheral_hits


def sort_key(paper: dict[str, Any]) -> tuple[int, int, str, str]:
    published = str(paper.get("published") or "")
    return (
        int(paper.get("score", 0)),
        len(paper.get("matched_terms", [])),
        published,
        str(paper.get("title") or ""),
    )


def triage(papers: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for paper in papers:
        combined = normalize_text(f"{paper.get('title', '')} {paper.get('abstract', '')}")
        track, score, matched_terms = classify_track(combined, cfg)
        enriched_paper = dict(paper)
        enriched_paper["track"] = track
        enriched_paper["score"] = score
        enriched_paper["matched_terms"] = matched_terms
        enriched.append(enriched_paper)

    score3 = sorted((paper for paper in enriched if paper["score"] == 3), key=sort_key, reverse=True)
    score2 = sorted((paper for paper in enriched if paper["score"] == 2), key=sort_key, reverse=True)
    max_selected = int(cfg.get("max_selected_papers", 10))
    remaining = max(max_selected - len(score3), 0)
    selected = score3 + score2[:remaining]
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage Togo-box candidates into selected.json")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    cfg = load_config(Path(args.config).expanduser().resolve())
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    papers = json.loads(input_path.read_text(encoding="utf-8-sig"))
    selected = triage(papers, cfg)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(selected, indent=2, ensure_ascii=False), encoding="utf-8")

    score3 = sum(1 for paper in selected if paper["score"] == 3)
    score2 = sum(1 for paper in selected if paper["score"] == 2)
    print(
        "[triage] "
        f"input={len(papers)} selected={len(selected)} "
        f"score3={score3} score2={score2} -> {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
