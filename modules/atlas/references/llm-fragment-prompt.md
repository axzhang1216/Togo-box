# LLM Memory Planning Prompt

Use this prompt to convert one source note into agent-callable long-term memory.

Do not use keyword rules, paragraph splitting, or regex extraction for semantic choices. Code may discover files, read files, search existing entities, validate JSON, and apply plans. The LLM must decide what is worth remembering, how to phrase it, which entities exist, and which relationships matter.

## Prompt

You are building a personal workflow memory palace for an AI agent.

Read the full Markdown source note. Output a JSON memory plan that stores only durable, useful, source-traceable memories. The future agent should be able to answer questions, resume projects, apply rules, recover decisions, find resources, and understand user context from this memory graph.

Root requirement: transform multi-source personal information into a database that AI agents can call cheaply, quickly, and accurately. Use first principles and Occam's razor. Only create fragments, entities, relations, retrieval fields, or freshness metadata when they improve retrieval accuracy, speed, cost, traceability, or maintainability.

Retrieval must be hybrid. The memory should support semantic-ready search through natural-language summaries and graph context, and lexical search through aliases/query phrases. If an embedding index exists, these semantic fields should be embed-ready. If no embedding index exists, these fields should still help an LLM rerank a small candidate set. Do not turn the system into keyword-only RAG.

## Core Objective

Every memory fragment must justify its existence:

- Will a future agent need this to answer the user accurately?
- Will this help resume a project, debug an issue, apply a policy, find a resource, or recall a decision?
- Can this be traced back to source text?

If the answer is no, omit it.

## Coarse Filtering

Use loose, broad labels to make first-pass retrieval cheaper. Do not over-engineer taxonomy.

The note may include:

- `source_type`: `markdown`, `pdf`, `chat`, `image`, `code`, `user_supplement`, or `other`.
- `domain`: broad user-facing areas such as `科研`, `日程`, `工作流`, `论文`, `数据管理`, `个人偏好`, `杂项`.

Fragments may override `domain` or `source_type` only when a fragment is clearly different from its source note.

## Memory Roles

Use exactly one `memory_role` per fragment:

- `fact`: stable description or fact.
- `rule`: standing rule, policy, requirement, invariant, threshold, permission, or prohibition.
- `decision`: choice made among alternatives.
- `finding`: observation, diagnosis, analysis result, or conclusion.
- `open_question`: unresolved question or uncertainty.
- `procedure`: repeatable workflow, process, or steps.
- `task`: todo, reminder, follow-up, deadline, next action.
- `preference`: user/team preference, style, convention, or operating principle.
- `resource`: reusable resource: server, dataset, file, tool, link, document, code, capability.
- `context`: background that makes other memories interpretable but is not independently actionable.

Do not output `ASSERT`, `CONSTRAIN`, `DECIDE`, `FIND`, `DO`, `ASK`, or `REMIND` unless converting a legacy plan.

## Fragment Rules

1. Split by memory value, not by paragraph.
2. A fragment is one reusable memory unit.
3. Preserve important thresholds, quantities, dates, paths, IPs, project names, people, and conditions.
4. Summarize lists when the list is one policy or workflow.
5. Split list items when each item is a separately reusable rule/fact.
6. Omit formatting-only text, image embeds, attachment paths, markdown anchors, duplicated headings, random IDs, and generic boilerplate.
7. Do not hallucinate. If uncertain, put the uncertainty in `quality_checks.open_questions`.

## Entity Ontology

Use these entity types:

- `thing`: stable object over time: project, model, dataset, server, cluster, storage tier, method, policy document, software, codebase, config, paper, location, resource.
- `actor`: person, team, organization, institution, or role-bearing group.
- `event`: bounded occurrence: meeting, experiment, debug session, conference, discussion, trip.
- `statement`: proposition that can be true/false, active/stale, resolved/unresolved: rule, decision, finding, hypothesis, question, task, constraint.

The source `note` is a container, not normally an entity.

## Entity Boundary Rules

Create/link an entity only when it improves future retrieval or reasoning.

Good entities:

- Named projects, models, datasets, servers, clusters, storage tiers, methods, tools, papers, repositories, policies, people, teams, organizations.
- Reusable rules/decisions/findings/questions/tasks as `statement`.

Bad entities:

- Image filenames, attachment paths, Markdown anchors, random IDs, URLs alone.
- Generic nouns like `CPU`, `home`, `data`, `scratch`, `README` unless the fragment is about a specific reusable object or policy.
- Section headings that are not reusable objects.
- Long variable/species lists as separate entities unless a variable/species is central to the memory.
- Noun phrases as `statement`.

Statement rules:

- A `statement.title` must be a concise proposition.
- Good: `服务器 home 数据占用率应低于 75%`.
- Bad: `高优先级存储` (this is a `thing`).
- Bad: `数据的标签` (probably a method/thing, unless phrased as a rule).

## Entity Kind Guidance

Thing kinds:

- `model`: GEOS-Chem, WRF-GC, WRF-Chem, CNN forecast model.
- `dataset`: observational dataset, model output, simulation result collection.
- `code`: repository, script, code archive.
- `config`: namelist, rc file, settings file, metadata README.
- `method`: workflow, algorithm, management scheme, simplification scheme.
- `tool`: software, database website, NAS service, sync platform.
- `location`: server, cluster, disk, storage server, storage tier, named path.
- `project`: research project or operational forecast project.
- `paper`: paper or publication.
- `other`: only when none fit.

Statement kinds:

- `rule`, `constraint`, `decision`, `finding`, `hypothesis`, `question`, `task`, `other`.

Actor kinds:

- `person`, `team`, `organization`.

Event kinds:

- `meeting`, `experiment`, `debug`, `discussion`, `conference`, `travel`, `other`.

## Relations

Add `relations` when they improve retrieval or reasoning. Use concise typed edges:

- `part_of`
- `uses`
- `used_by`
- `supports`
- `depends_on`
- `constrains`
- `owned_by`
- `managed_by`
- `stored_in`
- `derived_from`
- `supersedes`
- `answers`
- `raises`
- `next_action_for`
- `related_to`

Do not add edges just because two entities co-occur.

## Retrieval Fields

Each fragment must include a `retrieval` object:

- `semantic_summary`: one short natural-language summary optimized for embedding/semantic retrieval.
- `direct_queries`: likely user questions that explicitly mention this memory.
- `indirect_queries`: likely user questions that do not mention the exact entity name but should still retrieve it.
- `aliases`: synonyms, abbreviations, alternate English/Chinese names, file/path nicknames.
- `broader_topics`: parent topics that should semantically connect to this memory.

Example: an oversampling memory should be retrievable by both `oversampling` and broader phrases like `卫星数据后处理`, `遥感 L2 到 L3`, `卫星像元重网格`, `regridding`, and `satellite post-processing`.

Keep retrieval cues compact:

- Usually 2-4 `direct_queries`.
- Usually 2-4 `indirect_queries`.
- Usually 1-5 `aliases`.
- Usually 1-4 `broader_topics`.
- Prefer high-signal recall cues over exhaustive keyword stuffing.

## Freshness and Pollution Control

Every fragment should include:

- `status`: `active`, `stale`, `deprecated`, `superseded`, `resolved`, or `uncertain`.
- `created_at`: date when this memory was created or extracted, `YYYY-MM-DD`.
- `last_verified`: date when this memory was last verified, `YYYY-MM-DD`.

Use stricter freshness for operational memories: paths, server locations, dependencies, scripts, credentials-free access details, ownership, active decisions, and task status. If the source is old or uncertain, use `status: uncertain` and explain in `quality_checks.open_questions`.

If a new memory supersedes an older one, do not keep both as active. Mark the old one `superseded` or create a `supersedes` relation.

During retrieval, stale/uncertain memories may still be useful, but deprecated and superseded memories should not be treated as current truth unless the user asks for history.

## Output JSON

Output only valid JSON:

```json
{
  "note": {
    "title": "Original note title",
    "slug": "stable-kebab-slug",
    "source_path": "relative/path/from/vault.md",
    "source_type": "markdown|pdf|chat|image|code|user_supplement|other",
    "domain": ["broad", "loose", "areas"],
    "tags": ["small", "useful", "tags"]
  },
  "fragments": [
    {
      "memory_role": "fact|rule|decision|finding|open_question|procedure|task|preference|resource|context",
      "content": "Concise memory faithful to the source.",
      "source_excerpt": "Short source span supporting the memory.",
      "why_remember": "Why a future agent should remember this.",
      "retrieval": {
        "semantic_summary": "Short semantic summary for embedding retrieval.",
        "direct_queries": ["How the user might ask for this memory explicitly."],
        "indirect_queries": ["How the user might ask for this without exact entity names."],
        "aliases": ["synonym", "abbreviation", "alternate name"],
        "broader_topics": ["parent topic", "related workflow area"]
      },
      "status": "active|stale|deprecated|superseded|resolved|uncertain",
      "created_at": "YYYY-MM-DD",
      "last_verified": "YYYY-MM-DD",
      "source_evidence": [
        {
          "type": "markdown|image|user_supplement|code|other",
          "path": "relative/source/path",
          "locator": "page/section/image/line/function when available",
          "detail": "What was observed in this evidence."
        }
      ],
      "tags": ["optional", "topic"],
      "entities": [
        {
          "type": "thing|actor|event|statement",
          "title": "Entity title",
          "kind": "schema-kind",
          "description": "Only when useful for new entities"
        }
      ],
      "relations": [
        {"from": "Entity title", "type": "constrains", "to": "Other entity title"}
      ]
    }
  ],
  "quality_checks": {
    "omitted_noise": ["What was intentionally ignored."],
    "entity_boundary_notes": ["Hard entity/statement choices."],
    "open_questions": ["Human review questions."]
  }
}
```

## Output Requirements

- Output valid JSON only. No Markdown fences.
- Use Chinese when the source is Chinese.
- Keep `content` readable; it may summarize but must not change meaning.
- Every fragment must include `memory_role`, `content`, `source_excerpt`, `why_remember`, `retrieval`, `status`, `created_at`, and `last_verified`.
- `source_evidence` is required when information comes from images, user supplements, code files, or non-obvious evidence outside the plain Markdown text.
- Use `source_evidence.locator` when a source is long or non-linear: PDF page, Markdown section, image filename, code file line/function, chat date, or supplement date.
- Every entity must include `type`, title/name, and `kind`.
- Actor entities may include both `title` and `name`; keep them identical unless there is a reason not to.
- Prefer fewer high-quality fragments over exhaustive extraction.

## Gold-Standard Heuristics: Fugroup Data Management Note

For `Fugroup数据与存储管理手册.md`, good entities include:

- `fu01`, `forecast`, `b01`, `GPU 服务器`, `太乙超算集群`, `启明超算集群`, `梧桐存储服务器`, `NAS 存储服务器`, `离线存储硬盘` as `thing.kind=location`.
- `高优先级存储`, `低优先级存储`, `离线存储` as `thing.kind=location`.
- `在职同事数据管理方案`, `离职同事数据处理方案`, `默认模拟简化方案`, `数据标签 README` as `thing.kind=method` or `config` for README.
- `课题组`, `在职同事`, `离职同事`, `Aoxing` as `actor` only when responsibility/contact/ownership matters.
- `GEOS-Chem`, `WRF-GC`, `WRF-Chem`, `CNN 深圳预报`, `CNN 珠三角预报` as `thing.kind=model` or `project`.

Good memory fragments include:

- `rule`: `每个服务器的 home 文件夹数据占用率应低于 75%。`
- `rule`: `不能在 home 文件夹中进行大规模文件写入。`
- `rule`: `找不到数据来源或无法确定数据内容的数据，应删除。`
- `resource`: `fu01 是 IP 为 172.18.31.50 的课题组服务器，承担 CNN 深圳预报日常运算。`
- `procedure`: `已经发表文章所使用的数据应整理、打标签、打包，上传公开数据库获得 DOI，然后存入离线存储。`
- `procedure`: `测试/debug 用数据如果 1 个月内仍在使用，应放在高优先级存储；否则保留设定文件和代表性输出，删除其他文件。`

Bad memories/entities include:

- One fragment for every bullet if the bullets only describe one server or one workflow.
- `CPU`, `总存储`, `home`, `data`, `scratch` as free-floating entities.
- `Pasted image...png`, block anchors such as `^5424ac`, and heading links as entities.
- `高优先级存储` as a statement; it is a thing.
