# Paper Memory Guide

Use this guide when Togo-box reads papers and needs a JSON memory artifact in addition to the human-readable Markdown report.

The paper memory must use the same Atlas plan shape as notes:

- one top-level `note`
- durable `fragments`
- source-traceable evidence
- entities and relations only when they improve future recall
- retrieval fields that support direct, indirect, and vector recall

Do not create a separate paper-only memory ontology. Papers are another source type handled by Atlas.

## Output Location

For each selected paper, write one JSON file:

```text
output/memory/<paper-slug>.memory.json
```

This file is an Atlas memory plan. It can be validated or applied later with:

```bash
python modules/atlas/tools/wiki_fragment.py validate --plan output/memory/<paper-slug>.memory.json
python modules/atlas/tools/wiki_fragment.py apply --plan output/memory/<paper-slug>.memory.json
```

## Paper Note Fields

Use:

```json
{
  "note": {
    "title": "Paper title",
    "slug": "stable-paper-slug",
    "source_path": "output/fulltext/<paper-slug>.txt",
    "source_type": "pdf",
    "domain": ["科研", "论文"],
    "tags": ["paper", "atmospheric-chemistry"]
  }
}
```

Use `source_type: "pdf"` when the full text came from PDF, even if Atlas reads the extracted `.txt`. Use `source_type: "other"` only when the source was neither PDF nor HTML.

## Optional Paper Profile

Add `paper_profile` when the paper was read deeply. It is for fast human/agent orientation, not a replacement for fragments:

```json
{
  "paper_profile": {
    "citation_key": "2026_firstauthor_short-title",
    "title": "Paper title",
    "authors": ["First Author", "Second Author"],
    "year": "2026",
    "doi": "",
    "journal": "",
    "research_question": "What problem the paper answers.",
    "methods": ["method or model names"],
    "datasets": ["dataset names"],
    "main_findings": ["short finding"],
    "limitations": ["paper-stated limitation"],
    "open_data": ["URL/DOI/resource or None stated"],
    "use_for_my_work": "Why this matters to the user's research memory.",
    "do_not_overclaim": ["boundaries the paper does not prove"]
  }
}
```

## Fragment Selection

Prefer 3-7 fragments per full paper:

- `finding`: main result that may be useful later.
- `procedure`: method chain worth reusing or comparing.
- `resource`: dataset, code, model, benchmark, archive, or open data URL.
- `rule`: practical scientific constraint or interpretation boundary.
- `open_question`: unresolved limitation, caveat, or future work that matters.
- `context`: background only when it helps interpret the paper later.

Avoid one fragment per section. Do not store generic introduction prose unless it changes future retrieval or reasoning.

## Entity Guidance For Papers

Good entities:

- the paper itself as `thing.kind=paper`
- named datasets, models, instruments, chemical mechanisms, field campaigns, code repositories, and methods
- corresponding authors or research groups only when ownership/contact matters
- reusable claims as `statement`

Avoid entities for:

- every author in a long author list
- generic words such as `model`, `dataset`, `experiment`, `ozone`, or `aerosol` unless the paper is about a specific named object
- URLs alone
- figure numbers unless a specific figure is the evidence anchor

## Retrieval Cues

Each fragment should include:

- explicit queries: paper title, method name, dataset name, main result
- indirect queries: broader problem the paper helps answer
- aliases: abbreviations, Chinese/English variants, model/dataset nicknames
- broader topics: atmospheric chemistry, satellite retrieval, emissions, ML surrogate, uncertainty, etc.

Example indirect queries:

- `有哪些论文能支持卫星反演不确定度分析`
- `空气质量模型替代模型有哪些方法`
- `哪个研究提供了开放的排放清单数据`
- `论文里有没有可复用的 HCHO 反演方法`

## Evidence

For ordinary extracted full text, `source_evidence.path` is enough:

```json
{
  "type": "pdf",
  "path": "output/fulltext/<paper-slug>.txt",
  "detail": "Full-text extraction from selected paper."
}
```

Use `locator` only when needed: PDF page, section title, figure/table number, supplement file, or code repository path. Do not spend tokens inventing precise locators for short extracted text.

## Quality Gate

Before saving:

- the JSON validates as an Atlas plan
- every fragment answers why a future agent should remember it
- limitations and caveats come from the paper, not inference
- open data/code entries are real URLs/DOIs or `None stated`
- retrieval cues include at least one indirect query that does not name the paper
- the memory does not overclaim beyond the paper's evidence
