---
name: atlas
description: "Use as the Togo-box memory core when converting personal materials into a cheap, fast, accurate AI-agent memory database: Obsidian notes, project materials, decisions, rules, resources, papers, chats, images, and workflow knowledge become source-traceable memory fragments, entities, links, lexical indexes, and optional vector indexes."
---

# Atlas

Build an agent memory graph from source notes.

The goal is not to make pretty Wiki pages or classify prose. The goal is to digest user materials into structured, source-traceable working memory so future agents can accurately answer questions, resume projects, recover decisions, apply rules, and find resources.

## Root Requirement

The user's root goal is to transform multi-source personal information into a database that AI agents can call cheaply, quickly, and accurately.

All future changes must serve this goal. Use first principles and Occam's razor:

- Keep structures only when they improve retrieval accuracy, speed, cost, traceability, or maintainability.
- Prefer the simplest schema that reliably supports the target retrieval behavior.
- Do not add fields, entity types, indexes, workflows, or graph edges because they are theoretically elegant.
- Evaluate every change by asking: does this make future agent recall cheaper, faster, or more accurate?
- Preserve raw sources as evidence; structured memory is the retrieval layer, not a replacement for evidence.

## Core Model

- **Source note**: raw evidence container. Never modify it.
- **Memory fragment**: one reusable memory unit worth retrieving later.
- **Entity**: stable node in the memory graph: `thing`, `actor`, `event`, `statement`, or `note`.
- **Statement**: a proposition: rule, decision, finding, open question, task, hypothesis, constraint. It must not be a noun phrase.
- **Edge/link**: a relationship that improves future retrieval or reasoning.
- **Retrieval index**: cheap first-pass index. Search it before opening full Wiki files or raw sources.

Retrieval is hybrid:

- Semantic-ready retrieval should use `content`, `semantic_summary`, entities, and relations. If embeddings exist, use them; otherwise use these fields as LLM-readable semantic candidates.
- Lexical retrieval should use direct queries, indirect queries, aliases, and broader topics.
- Keyword fields are recall aids, not a replacement for semantic search or the graph.
- Broad `domain` and `source_type` fields may be used for cheap coarse filtering before lexical/semantic ranking. Keep them loose; do not over-engineer taxonomy.

## Required References

Read these before planning:

- `references/llm-fragment-prompt.md` — required LLM planner prompt and quality rules.
- `references/entity-schema.md` — entity file schemas.

Read only for legacy migration:

- `references/fragment-types.md` — old `ASSERT/DECIDE/FIND/DO/ASK/REMIND/CONSTRAIN` taxonomy. Do not use by default.

## Tools

```bash
WIKI="output/atlas-wiki"
SKILL="modules/atlas"

python "$SKILL/tools/wiki_gate.py" "<query>"
python "$SKILL/tools/wiki_gate.py" "<query>" --search
python "$SKILL/tools/wiki_fragment.py" plan --source "<path>"
python "$SKILL/tools/wiki_fragment.py" validate --plan <plan.json>
python "$SKILL/tools/wiki_fragment.py" apply --plan <plan.json>
python "$SKILL/tools/wiki_memory_search.py" "<query>" --limit 10
python "$SKILL/tools/wiki_memory_search.py" "<query>" --domain 科研 --source-type markdown --llm-pack
python "$SKILL/tools/wiki_memory_vector.py" build
python "$SKILL/tools/wiki_memory_vector.py" search "<query>" --domain 科研 --limit 10
python "$SKILL/tools/wiki_memory_audit.py" --output "$WIKI/build-reports/memory-audit.json"
python "$SKILL/tools/wiki_search.py" "<query>" --type <thing|actor|event|statement>
```

## Gating Conventions

Atlas retrieval should respect source-specific gating conventions.

- `日常习惯约定`:
  default front-memory for code habits, interests, and recurring corrections from chat history.
- `论文门控约定`:
  do not search paper memory in ordinary chat; only open it for research/paper/literature/method contexts.
- `笔记门控约定`:
  open only when the user is asking the agent to recall previous notes, discussions, or historical context.

Read `references/gating-conventions.md` and use `gating_conventions.json` as the active config.

## Workflow

### 1. Discover Sources

List source `.md` files outside `Wiki/`. Skip binary-like, empty, generated, or attachment-heavy files unless the user explicitly wants them.

### 2. Generate Memory Plan With LLM

For each source note:

1. Read full Markdown using the correct encoding.
2. Use `references/llm-fragment-prompt.md`.
3. Decide what is worth remembering for future agent use.
4. Produce a JSON plan with `memory_role`, entities, semantic retrieval fields, freshness fields, and source evidence.
5. Search/dedup existing entities before applying.

Code may read files, search, validate JSON, and write deterministic output. Code must not decide fragment boundaries, memory roles, or entity types.

### 3. Plan Shape

```json
{
  "note": {
    "title": "Fugroup数据与存储管理手册",
    "slug": "fugroup-data-storage-management-manual",
    "source_path": "Fugroup数据与存储管理手册.md",
    "source_type": "markdown",
    "domain": ["科研", "数据管理"],
    "tags": ["数据管理", "存储", "课题组"]
  },
  "fragments": [
    {
      "memory_role": "rule",
      "content": "每个服务器的 home 文件夹数据占用率应低于 75%。",
      "source_excerpt": "每个服务器的home文件夹数据占用率小于75%",
      "why_remember": "未来判断服务器存储是否健康时需要应用该阈值。",
      "retrieval": {
        "semantic_summary": "服务器 home 目录占用率健康阈值规则。",
        "direct_queries": ["服务器 home 占用率限制是多少", "home 文件夹存储健康标准"],
        "indirect_queries": ["服务器存储健康检查", "课题组数据清理规则"],
        "aliases": ["home 目录", "home 文件夹"],
        "broader_topics": ["服务器存储管理", "数据管理规范"]
      },
      "status": "active",
      "created_at": "2026-06-23",
      "last_verified": "2026-06-23",
      "source_evidence": [
        {
          "type": "markdown",
          "path": "Fugroup数据与存储管理手册.md",
          "locator": "section: 存储健康",
          "detail": "原文给出 home 文件夹占用率阈值。"
        }
      ],
      "tags": ["存储健康", "规则"],
      "entities": [
        {"type": "thing", "title": "服务器 home 文件夹", "kind": "location"},
        {
          "type": "statement",
          "title": "服务器 home 数据占用率应低于 75%",
          "kind": "constraint",
          "status": "active",
          "confidence": "high"
        }
      ],
      "relations": [
        {"from": "服务器 home 数据占用率应低于 75%", "type": "constrains", "to": "服务器 home 文件夹"}
      ]
    }
  ],
  "quality_checks": {
    "omitted_noise": ["image embeds", "markdown anchors"],
    "entity_boundary_notes": [],
    "open_questions": []
  }
}
```

Valid `memory_role` values:

- `fact`: stable fact or description.
- `rule`: standing rule, policy, requirement, invariant, or constraint.
- `decision`: choice made among alternatives.
- `finding`: observed result, diagnosis, conclusion.
- `open_question`: unresolved question or uncertainty.
- `procedure`: repeatable workflow or steps.
- `task`: todo, reminder, follow-up.
- `preference`: user/team preference or operating style.
- `resource`: reusable file, tool, dataset, server, link, document, or capability.
- `context`: background that helps interpret other memory but is not independently actionable.

Do not add `type: ASSERT/CONSTRAIN/...` to new plans. The writer supports it only for old plans.

### 4. Quality Gate Before Apply

Reject or revise the plan if any are true:

- A fragment exists only because a paragraph existed.
- A `statement` title is a noun phrase instead of a proposition.
- A generic word, image, attachment, markdown anchor, random ID, or one-off variable became an entity.
- The fragment lacks `why_remember`.
- The fragment lacks `retrieval.semantic_summary`.
- The fragment lacks plausible direct or indirect retrieval cues.
- Operational/path/status memories lack `status` and `last_verified`.
- The plan cannot explain how the memory helps future agent recall or reasoning.

### 5. Apply

After review:

```bash
python "$SKILL/tools/wiki_fragment.py" apply --plan <plan.json>
```

The writer creates note/entity files, bidirectional mentioned-in links, and appends fragment index records. It is deterministic; it must not invent semantic structure.

It also upserts:

- `Wiki/fragments.jsonl`: full fragment index.
- `Wiki/retrieval_index.jsonl`: lightweight hybrid retrieval index with semantic summaries, direct/indirect queries, aliases, broader topics, entities, status, and verification date.
- `Wiki/retrieval_vectors.jsonl`: optional embedding index derived from `retrieval_index.jsonl`; rebuild it after retrieval index changes.

### 6. Retrieve Memory

Default retrieval should be cheap and staged:

1. Search `Wiki/retrieval_index.jsonl` with `wiki_memory_search.py`.
2. If the query clearly belongs to a broad area, filter with `--domain` or `--source-type` first. Examples: `科研`, `日程`, `工作流`, `论文`, `聊天记录`, `杂项`; `markdown`, `pdf`, `chat`, `image`, `code`, `user_supplement`.
3. For indirect or concept-heavy questions, search `Wiki/retrieval_vectors.jsonl` with `wiki_memory_vector.py search`.
4. Merge lexical and vector candidates into a small candidate set, usually 5-15 fragments.
5. Let an LLM rerank or decide whether the candidate set is sufficient.
6. Only then open the Wiki note or raw source evidence.

Do not make the taxonomy brittle. Coarse domain/source filters are for cutting search space, not for deciding truth.

Vector retrieval requires an OpenAI-compatible embeddings API:

- Set `OPENAI_API_KEY` or `WIKI_EMBEDDING_API_KEY`.
- Optional: set `OPENAI_BASE_URL` / `WIKI_EMBEDDING_BASE_URL`.
- Optional: set `OPENAI_EMBEDDING_MODEL` / `WIKI_EMBEDDING_MODEL`; default is `text-embedding-3-small`.
- The vector index is derived data. If `retrieval_index.jsonl` changes, rerun `python "$SKILL/tools/wiki_memory_vector.py" build`.

### 7. Audit Old Memory

Legacy batches may contain polluted entities such as image filenames, random IDs, short tokens, and path-like titles. Do not delete them blindly.

Run:

```bash
python "$SKILL/tools/wiki_memory_audit.py" --output "$WIKI/build-reports/memory-audit.json"
```

Use the report to review, merge, quarantine, or delete old artifacts later. Cleanup must preserve source traceability and must not remove user-authored source notes.

## User Supplements to Existing Notes

When the user provides new information about an existing source note:

1. Treat the user's message as source evidence.
2. Update the relevant memory plan or Wiki memory with a new or revised fragment.
3. Also append the supplement to the original Markdown source note, unless the user says not to.
4. Append only at the end of the source note using this format:

```markdown
YYYYMMDD关于此文件的补充：
<user-provided supplement>
```

5. Do not rewrite or reorganize the existing source note while appending a supplement.
6. If the supplement changes an existing memory, update that memory rather than creating a duplicate.
7. If the supplement is a path, file location, credential-free access detail, owner, status, or operational constraint, usually store it as `memory_role: resource`, `rule`, or `context` with retrieval queries.
8. Supplements about paths, server locations, dependencies, ownership, or status should set `last_verified` to the current date.

## Bulk Processing Rule

Do not bulk-apply unreviewed LLM output across the whole vault. First create and review gold-standard plans for representative notes, then process batches with sampling review.

## Non-Negotiables

- Only write generated memory to `Wiki/`. Do not rewrite source notes.
- Exception: when the user explicitly provides a supplement for an existing source note, append it to the source note using the supplement format above.
- Raw source remains the evidence layer; Wiki memory is the digested retrieval layer.
- Omega Wiki does not replace raw retrieval; it complements full-text/RAG by storing curated memory nodes.
- Prefer fewer high-quality memories over exhaustive extraction.
- Every memory must answer: “Why should a future agent remember this?”
