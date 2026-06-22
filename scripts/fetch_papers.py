#!/usr/bin/env python3
"""
togo-box / literature_radar / fetch_papers.py

Fetch candidate papers from arXiv and CrossRef, then resolve open-access PDFs
with Unpaywall. The script is intentionally dependency-light and can run from
any working directory.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SKILL_ROOT / "references" / "config.md"
DEFAULT_OUTPUT = SKILL_ROOT / "output" / "candidates.json"

ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def strip_inline_comment(value: str) -> str:
    """Strip markdown-style inline comments while preserving URLs."""
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
        "email": "user@example.com",
        "days_back": 7,
        "max_arxiv_results": 60,
        "max_crossref_rows": 25,
        "atmo_keywords": [],
        "ml_keywords": [],
        "journals": [],
        "arxiv_cats": ["physics.ao-ph", "cs.LG", "stat.ML"],
        "output_dir": "output/",
    }

    current_list_key: str | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        print(f"[warn] config not found at {path}; using defaults", file=sys.stderr)
        return cfg

    for raw in lines:
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


def normalize_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clean_markup(value: str | None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<\s*/?\s*(sub|sup|i|b|em|strong)\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_whitespace(text)


def request_headers(email: str) -> dict[str, str]:
    clean_email = email if "@" in email and "your@" not in email else "user@example.com"
    return {"User-Agent": f"togo-box/1.1 (mailto:{clean_email})"}


def fetch_text(url: str, params: dict[str, Any] | None, email: str, timeout: int) -> tuple[int, str]:
    if params:
        query = urllib.parse.urlencode(params)
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{query}"

    request = urllib.request.Request(url, headers=request_headers(email))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError:
                charset = response.headers.get_content_charset() or "utf-8"
                body = raw.decode(charset, errors="replace")
            return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body


def fetch_json(url: str, params: dict[str, Any] | None, email: str, timeout: int) -> tuple[int, dict[str, Any]]:
    status, body = fetch_text(url, params, email, timeout)
    if status >= 400:
        return status, {}
    return status, json.loads(body)


def fetch_arxiv(
    keywords: list[str],
    categories: list[str],
    days_back: int,
    email: str,
    max_results: int,
) -> list[dict[str, Any]]:
    if not keywords or not categories:
        return []

    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    cat_query = " OR ".join(f"cat:{category}" for category in categories)
    keyword_query = " OR ".join(f'all:"{keyword}"' for keyword in keywords[:10])
    query = f"({cat_query}) AND ({keyword_query})"
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    try:
        status, body = fetch_text("https://export.arxiv.org/api/query", params, email, 25)
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
    except (OSError, RuntimeError) as exc:
        print(f"[arXiv] error: {exc}")
        return []

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        print(f"[arXiv] parse error: {exc}")
        return []

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in root.findall("atom:entry", ARXIV_NS):
        raw_id = entry.findtext("atom:id", default="", namespaces=ARXIV_NS)
        arxiv_id = raw_id.split("/abs/")[-1].split("v")[0]
        if not arxiv_id or arxiv_id in seen:
            continue

        published = entry.findtext("atom:published", default="", namespaces=ARXIV_NS)
        try:
            published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if published_dt < since:
            continue

        authors = [
            normalize_whitespace(author.findtext("atom:name", default="", namespaces=ARXIV_NS))
            for author in entry.findall("atom:author", ARXIV_NS)
        ]
        title = normalize_whitespace(entry.findtext("atom:title", default="", namespaces=ARXIV_NS))
        abstract = normalize_whitespace(entry.findtext("atom:summary", default="", namespaces=ARXIV_NS))
        journal_ref = normalize_whitespace(
            entry.findtext("arxiv:journal_ref", default="", namespaces=ARXIV_NS)
        )

        seen.add(arxiv_id)
        results.append(
            {
                "source": "arxiv",
                "arxiv_id": arxiv_id,
                "doi": None,
                "title": title,
                "authors": [author for author in authors if author][:6],
                "published": published[:10],
                "abstract": abstract,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "landing_url": f"https://arxiv.org/abs/{arxiv_id}",
                "venue": journal_ref or "arXiv preprint",
            }
        )

    print(f"[arXiv] {len(results)} papers found")
    return results


def crossref_published_date(item: dict[str, Any]) -> str:
    parts = item.get("published", {}).get("date-parts", [[]])
    if not parts or not parts[0]:
        return "unknown"
    return "-".join(str(part) for part in parts[0])


def parse_crossref_date(value: str) -> datetime | None:
    if not value or value == "unknown":
        return None
    parts = [int(part) for part in value.split("-") if part.isdigit()]
    if not parts:
        return None
    while len(parts) < 3:
        parts.append(1)
    try:
        return datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_crossref(
    keywords: list[str],
    journals: list[str],
    days_back: int,
    email: str,
    rows: int,
) -> list[dict[str, Any]]:
    if not keywords:
        return []

    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
    until = now.strftime("%Y-%m-%d")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for keyword in keywords[:8]:
        params = {
            "query": keyword,
            "filter": f"from-pub-date:{since},until-pub-date:{until},type:journal-article",
            "select": "DOI,title,author,published,abstract,container-title,URL",
            "rows": rows,
            "mailto": email,
        }
        try:
            status, data = fetch_json("https://api.crossref.org/works", params, email, 15)
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
            items = data.get("message", {}).get("items", [])
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"[CrossRef] error for {keyword!r}: {exc}")
            items = []

        for item in items:
            doi = (item.get("DOI") or "").lower().strip()
            if not doi or doi in seen:
                continue

            venue = normalize_whitespace(" ".join(item.get("container-title", [])))
            if journals and not any(journal.lower() in venue.lower() for journal in journals):
                continue

            published = crossref_published_date(item)
            published_dt = parse_crossref_date(published)
            if published_dt and published_dt > now:
                continue

            authors = [
                normalize_whitespace(f"{author.get('given', '')} {author.get('family', '')}")
                for author in item.get("author", [])[:6]
            ]
            titles = item.get("title", ["(no title)"])
            title = clean_markup(titles[0] if titles else "(no title)")
            abstract = clean_markup(item.get("abstract"))

            seen.add(doi)
            results.append(
                {
                    "source": "crossref",
                    "arxiv_id": None,
                    "doi": doi,
                    "title": title,
                    "authors": [author for author in authors if author],
                    "published": published,
                    "abstract": abstract,
                    "pdf_url": None,
                    "landing_url": f"https://doi.org/{doi}",
                    "venue": venue,
                }
            )

        time.sleep(0.6)

    print(f"[CrossRef] {len(results)} papers found")
    return results


def resolve_unpaywall(papers: list[dict[str, Any]], email: str) -> list[dict[str, Any]]:
    if "@" not in email or "your@" in email:
        print("[Unpaywall] skipped; set a real email in references/config.md")
        return papers

    resolved = 0
    for paper in papers:
        doi = paper.get("doi")
        if not doi or paper.get("pdf_url"):
            continue
        try:
            status, data = fetch_json(f"https://api.unpaywall.org/v2/{doi}", {"email": email}, email, 10)
            if status == 404:
                paper["is_oa"] = False
                continue
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
            best = data.get("best_oa_location") or {}
            url = best.get("url_for_pdf") or best.get("url")
            if url:
                paper["pdf_url"] = url
                resolved += 1
            paper["is_oa"] = data.get("is_oa", False)
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"[Unpaywall] {doi}: {exc}")
        time.sleep(0.25)

    print(f"[Unpaywall] resolved {resolved} OA PDFs")
    return papers


def deduplicate(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_doi: set[str] = set()
    seen_arxiv: set[str] = set()
    seen_title: set[str] = set()
    out: list[dict[str, Any]] = []

    for paper in papers:
        doi = paper.get("doi") or ""
        arxiv_id = paper.get("arxiv_id") or ""
        title_key = re.sub(r"[^a-z0-9]", "", (paper.get("title") or "").lower())[:80]
        if (doi and doi in seen_doi) or (arxiv_id and arxiv_id in seen_arxiv) or title_key in seen_title:
            continue
        if doi:
            seen_doi.add(doi)
        if arxiv_id:
            seen_arxiv.add(arxiv_id)
        if title_key:
            seen_title.add(title_key)
        out.append(paper)

    return out


def resolve_output_path(output_arg: str | None, cfg: dict[str, Any]) -> Path:
    if output_arg:
        return Path(output_arg).expanduser().resolve()

    output_dir = Path(str(cfg.get("output_dir", "output/")))
    if not output_dir.is_absolute():
        output_dir = SKILL_ROOT / output_dir
    return output_dir / "candidates.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch paper candidates for Togo-box literature radar.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to config.md")
    parser.add_argument("--output", default=None, help="Path to write candidate JSON")
    parser.add_argument("--dry-run", action="store_true", help="Load config and print planned settings without network calls")
    parser.add_argument("--skip-unpaywall", action="store_true", help="Skip DOI to OA PDF resolution")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_path = Path(args.config).expanduser().resolve()
    cfg = load_config(config_path)

    email = str(cfg.get("email", "user@example.com")).strip()
    days_back = int(cfg.get("days_back", 7))
    max_arxiv_results = int(cfg.get("max_arxiv_results", 60))
    max_crossref_rows = int(cfg.get("max_crossref_rows", 25))
    keywords = list(cfg.get("atmo_keywords", [])) + list(cfg.get("ml_keywords", []))
    output_path = resolve_output_path(args.output, cfg)

    print(
        "[togo-box/fetch] "
        f"window={days_back}d keywords={len(keywords)} "
        f"arxiv_cats={len(cfg.get('arxiv_cats', []))} output={output_path}"
    )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "config": str(config_path),
                    "output": str(output_path),
                    "email": email,
                    "days_back": days_back,
                    "keywords": len(keywords),
                    "journals": len(cfg.get("journals", [])),
                    "arxiv_cats": cfg.get("arxiv_cats", []),
                    "max_arxiv_results": max_arxiv_results,
                    "max_crossref_rows": max_crossref_rows,
                },
                indent=2,
            )
        )
        return 0

    papers = fetch_arxiv(
        keywords,
        list(cfg.get("arxiv_cats", [])),
        days_back,
        email,
        max_arxiv_results,
    )
    papers.extend(
        fetch_crossref(
            keywords,
            list(cfg.get("journals", [])),
            days_back,
            email,
            max_crossref_rows,
        )
    )
    papers = deduplicate(papers)
    if not args.skip_unpaywall:
        papers = resolve_unpaywall(papers, email)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(papers, indent=2, ensure_ascii=False), encoding="utf-8")

    oa_count = sum(1 for paper in papers if paper.get("pdf_url"))
    print(f"[togo-box/fetch] done: {len(papers)} candidates, {oa_count} with OA PDF -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
