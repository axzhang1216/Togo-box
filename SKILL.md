---
name: togo-box
description: >
  Token-burning research intelligence skill for when weekly quota would otherwise go unused.
  Use for Togo-box, togo box, token burn, quota burn, literature radar, weekly paper scans,
  atmospheric chemistry papers, AI/ML for science papers, full-text paper reading, open data/code
  extraction from papers, concise high-signal research briefings, and Atlas memory JSON. Fetch
  candidates, triage, read full text, produce a Chinese-readable report with detailed qualitative
  methods, and write agent-callable memory artifacts.
---

# Togo-box

Use this skill when the user wants to spend unused quota on useful information gathering. The default workflow is a literature radar: fetch current papers, triage them, read selected full text, write a compact briefing, and create Atlas memory JSON for future agent recall.

Load `references/config.md` first, then load the matching workflow reference.

## Internal Modules

| Module | Use | Location |
|--------|-----|----------|
| `atlas` | Memory core for source-traceable fragments, entities, retrieval indexes, and optional vectors | `modules/atlas` |

## Memory Routing

Atlas memory is not one flat retrieval pool.

- `日常习惯约定`:
  front-memory for the user's coding habits, interest directions, and recurring correction points from chat history.
- `论文门控约定`:
  only open paper memory for research / paper / literature / method related discussion.
- `笔记门控约定`:
  only open historical note memory when the user is clearly asking the agent to recall earlier notes, discussions, or daily context.

For Atlas retrieval, prefer `modules/atlas/tools/wiki_gate.py` over raw broad search when routing matters.

## Workflows

| Workflow | Use when the user asks for | Reference |
|----------|----------------------------|-----------|
| `literature_radar` | scan papers, literature radar, catch me up, weekly research, burn quota for research info, read selected atmospheric chemistry or AI/ML papers | `references/research_paper_read.md` |

## Routing

1. Read the user's request.
2. Load `references/config.md`.
3. Match the request to a workflow.
4. Load the corresponding reference file.
5. Follow that workflow exactly, using bundled scripts when available.

If multiple workflows apply, handle them sequentially unless the user asks for a different order.

## Output Style

- Prefer Chinese for paper conclusions, method explanations, limitations, and synthesis unless the user asks otherwise.
- Keep titles, links, venue names, model names, dataset names, and code/data resource names in their original language when clearer.
- For each paper, make the `Method` field explain the analysis chain from source data or hypothesis to conclusion, including the qualitative proof logic and the diagnostic quantities used.
- For each selected paper, also create `output/memory/<paper-slug>.memory.json` using `modules/atlas/references/paper-memory.md`.

## Development Notes

- Keep `SKILL.md` short; put detailed workflows in `references/`.
- Keep scripts deterministic and runnable from any working directory.
- Do not commit generated reports, downloaded PDFs, extracted full text, or user-private configuration values.
