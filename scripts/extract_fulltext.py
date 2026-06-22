#!/usr/bin/env python3
"""
Extract readable text for selected Togo-box literature-radar papers.

Input:  output/selected.json
Output: output/fulltext/<slug>.txt and output/fulltext/manifest.json
"""

from __future__ import annotations

import argparse
import html
import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from pypdf import PdfReader


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SELECTED = SKILL_ROOT / "output" / "selected.json"
DEFAULT_OUTDIR = SKILL_ROOT / "output" / "fulltext"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:90] or "paper"


def headers() -> dict[str, str]:
    return {"User-Agent": "togo-box/1.1 literature-radar"}


def fetch_bytes(url: str, timeout: int = 45) -> tuple[str, bytes, str]:
    request = urllib.request.Request(url, headers=headers())
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = response.headers.get("content-type", "")
        return final_url, response.read(), content_type


def text_from_pdf(blob: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(blob)
        tmp_path = Path(tmp.name)
    try:
        reader = PdfReader(str(tmp_path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages)
    finally:
        tmp_path.unlink(missing_ok=True)


def text_from_html(blob: bytes) -> str:
    raw = blob.decode("utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)</(p|div|section|article|h[1-6]|li|tr)>", "\n", raw)
    raw = re.sub(r"(?is)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"[ \t\r\f\v]+", " ", raw).replace("\n ", "\n").strip()


def likely_pdf(url: str, content_type: str, blob: bytes) -> bool:
    return (
        "pdf" in content_type.lower()
        or urllib.parse.urlparse(url).path.lower().endswith(".pdf")
        or blob[:5] == b"%PDF-"
    )


def candidate_urls(paper: dict[str, Any]) -> list[str]:
    urls = []
    if paper.get("pdf_url"):
        urls.append(str(paper["pdf_url"]))
    arxiv_id = paper.get("arxiv_id")
    if arxiv_id:
        urls.append(f"https://arxiv.org/pdf/{arxiv_id}")
    if paper.get("landing_url"):
        urls.append(str(paper["landing_url"]))
    return list(dict.fromkeys(urls))


def extract_one(paper: dict[str, Any], outdir: Path) -> dict[str, Any]:
    title = paper.get("title") or "untitled"
    slug = slugify(title)
    errors = []
    for url in candidate_urls(paper):
        try:
            final_url, blob, content_type = fetch_bytes(url)
            if likely_pdf(final_url, content_type, blob):
                text = text_from_pdf(blob)
                mode = "pdf"
            else:
                text = text_from_html(blob)
                mode = "html"
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) < 1000:
                errors.append(f"{url}: too little text ({len(text)} chars)")
                continue
            text_path = outdir / f"{slug}.txt"
            text_path.write_text(text, encoding="utf-8")
            return {
                "title": title,
                "text_path": str(text_path),
                "fetch_url_used": final_url,
                "mode": mode,
                "chars": len(text),
                "abstract_only": False,
                "paywalled": False,
                "errors": errors,
            }
        except (OSError, urllib.error.URLError, ValueError, RuntimeError) as exc:
            errors.append(f"{url}: {exc}")

    text_path = outdir / f"{slug}.txt"
    fallback = paper.get("abstract") or ""
    text_path.write_text(fallback, encoding="utf-8")
    return {
        "title": title,
        "text_path": str(text_path),
        "fetch_url_used": None,
        "mode": "abstract",
        "chars": len(fallback),
        "abstract_only": True,
        "paywalled": bool(paper.get("doi")),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected", default=str(DEFAULT_SELECTED))
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    args = parser.parse_args()

    selected_path = Path(args.selected).expanduser().resolve()
    outdir = Path(args.outdir).expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    papers = json.loads(selected_path.read_text(encoding="utf-8-sig"))

    manifest = []
    for paper in papers:
        result = extract_one(paper, outdir)
        manifest.append(result)
        status = "abstract-only" if result["abstract_only"] else result["mode"]
        print(f"[{status}] {result['chars']:>7} chars | {result['title']}")

    manifest_path = outdir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[extract_fulltext] wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
