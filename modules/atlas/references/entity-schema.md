# Entity Schema Reference

## 5 Universal Entity Types

### thing — 持续存在的事物
Anything that exists over time: models, datasets, code, configs, methods, tools, papers, projects.

```yaml
---
title: ""
slug: ""
kind: ""          # Optional. Free-form sub-label. Examples: model, dataset, code, config, method, paper, project, tool
tags: []
project: ""       # link → thing (which project this belongs to)
related: []       # list_link → any entity
description: ""
mentioned_in: []  # list_link → note (auto-populated by fragments)
date_added: ""
date_updated: ""
---
```

### event — 发生过的事件
Meetings, experiments, debugging sessions, trips, conferences.

```yaml
---
title: ""
slug: ""
kind: ""          # meeting, experiment, debug, discussion, conference, travel, other
tags: []
date: ""          # When it happened
actors: []        # list_link → actor
related: []       # list_link → any entity
outcome: ""       # What came out of it
mentioned_in: []  # list_link → note
date_added: ""
---
```

### statement — 判断和结论
Decisions, findings, constraints, hypotheses, rules, questions, tasks.

```yaml
---
title: ""
slug: ""
kind: ""          # decision, finding, constraint, hypothesis, question, task, rule, other
status: active    # active | superseded | failed | resolved
confidence: ""    # high | medium | low | tentative
tags: []
source: []        # list_link → thing/event (what this is based on)
supersedes: ""    # link → statement (what old judgment this replaces)
related: []       # list_link → any entity
mentioned_in: []  # list_link → note
date_added: ""
---
```

### actor — 参与者
People, teams, organizations.

```yaml
---
name: ""          # Use 'name' instead of 'title' for actors
slug: ""
kind: ""          # person, team, organization
affiliation: ""
role: ""          # pi, student, postdoc, collaborator, advisor
research_areas: []
tags: []
related: []       # list_link → any entity
mentioned_in: []  # list_link → note
date_added: ""
---
```

### note — 笔记容器
A container for fragments. One note file = one original document.

```yaml
---
title: ""
slug: ""
source_path: ""   # Original file path (for traceability)
tags: []
fragment_count: 0 # Auto-populated
date_added: ""
---
```

## Slug Rules
- Lowercase, kebab-case
- For papers: `{year}_{first-author}_{short-title}`
- For events: `{date}_{short-title}`
- For actors: `{last-name}-{first-name}`
- For notes: use the original filename stem

## Deduplication
Before creating any entity, search for existing matches:
```bash
python tools/wiki_search.py "<title>" --type <type>
```
If a match exists (score >= 0.86), link to it instead of creating a new entity.
