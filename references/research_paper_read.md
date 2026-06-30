# literature_radar

Quota-burning weekly literature radar for atmospheric chemistry and AI/ML for science. The goal is to spend otherwise-unused quota on useful information: fetch current candidates, triage by abstract, read selected full text, extract open data/code, write a concise Chinese-readable briefing, and produce Atlas memory JSON for each read paper.

## Data Sources

| Source | Use | API key |
|--------|-----|---------|
| arXiv | Preprints in configured categories | No |
| CrossRef | Journal metadata and DOIs | No; use `mailto` |
| Unpaywall | Open-access PDF resolver | No; use `email` |

## Step 1: Fetch Candidates

Run from the skill root or from any working directory:

```bash
python scripts/fetch_papers.py
```

Optional explicit paths:

```bash
python path/to/togo-box/scripts/fetch_papers.py \
  --config path/to/togo-box/references/config.md \
  --output path/to/togo-box/output/candidates.json
```

The script reads `references/config.md`, scans the configured time window, deduplicates by DOI, arXiv ID, and title, resolves OA PDFs through Unpaywall, and writes `output/candidates.json`.

Candidate objects include:

```json
{
  "title": "...",
  "authors": ["..."],
  "published": "YYYY-MM-DD",
  "venue": "...",
  "doi": "...",
  "arxiv_id": "...",
  "abstract": "...",
  "pdf_url": "https://... or null",
  "landing_url": "https://...",
  "source": "arxiv | crossref"
}
```

## Step 2: Triage

Default automated path:

```bash
python scripts/triage_candidates.py
```

This reads `output/candidates.json`, uses the configured topic keywords plus built-in core terms, and writes `output/selected.json`.

Manual review is still allowed when needed. In either case, score each paper using title and abstract only.

| Score | Meaning |
|-------|---------|
| 3 | Core result or method directly relevant to the configured research tracks |
| 2 | Peripheral but useful adjacent method, dataset, or context |
| 1 | Keyword match only; drop |

Keep all score-3 papers plus score-2 papers up to `max_selected_papers` from config, default 10. Write `output/selected.json` with added fields:

```json
{
  "score": 3,
  "track": "atmo | ml | peripheral"
}
```

Score atmospheric chemistry as core when it includes a new chemistry mechanism, rate constant, observational constraint, retrieval method, emissions inventory, model improvement, field-campaign result, or source-attribution finding with chemistry implications.

Score AI/ML as core when it includes a neural emulator or surrogate model for atmospheric/climate simulation, physics-informed ML, an Earth-system foundation model, scientific uncertainty quantification, an autonomous-science workflow, or a spatiotemporal method demonstrated on geophysical data.

## Step 3: Extract Full Text

Run:

```bash
python scripts/extract_fulltext.py
```

This reads `output/selected.json`, tries `pdf_url`, arXiv PDF, and landing page HTML, then writes:

- `output/fulltext/<paper-slug>.txt`
- `output/fulltext/manifest.json`

If a fetch fails or returns no useful body, keep the abstract and mark `abstract_only: true`. Never stall on one paper.

## Step 4: Read Papers

Process score-3 first, then score-2. Read nonlinearly:

1. Author block and affiliations
2. Abstract
3. Conclusion or summary
4. Methods and data
5. Results and figures with the strongest quantitative evidence
6. Data/code availability and supplement links
7. Limitations, caveats, uncertainty, and future-work statements

Extract exactly these fields for each selected paper and write `output/notes.json`:

```yaml
corresponding_author:
  name: Full name, or all corresponding authors
  affiliation: Full institution and department if given
  email: Email if present
main_conclusions:
  - Chinese bullet with concrete claim and numbers when the paper gives numbers
how_they_proved_it:
  study_design: Chinese one-sentence study type
  data_used: Dataset names, time period, spatial coverage
  method: Chinese qualitative analysis chain from origin to conclusion
  key_numbers: The 2-5 quantities that actually support the conclusion
limitations:
  - Chinese bullet from the paper itself
open_data:
  - Resource, URL or DOI, and platform
abstract_only: true | false
paywalled: true | false
fetch_url_used: URL actually fetched
```

### Method Field Standard

For every full paper, the `method` field must be detailed enough that a reader can understand the proof logic without rereading the paper. Do not merely say "they used a model" or "they used ML".

Include:

- the starting data, hypothesis, or perturbation design
- the comparison/control structure
- the processing or modeling chain
- the intermediate diagnostic quantities
- how those quantities connect to the final conclusion

Formulas can be omitted unless essential. Qualitative causal or statistical logic must not be omitted.

Examples of acceptable diagnostic quantities:

- source-removal O3 contribution such as `O3,FF` and `O3,BB`
- retrieval validation metrics such as `CV-R2`, `RMSE`, bias, or recovery time
- radiative forcing, burden/column change, lifetime change, or normalized sensitivity
- emission flux bias, concentration bias, SOA yield, aging response, or precursor ranking
- condensation sink, O3/oxidation capacity, boundary-layer height, SHAP contribution
- trend, 2-sigma uncertainty, drift diagnostics, proxy contribution, or R2 improvement

## Step 5: Create Atlas Paper Memory

For every selected paper, also write one Atlas memory plan:

```text
output/memory/<paper-slug>.memory.json
```

Use `modules/atlas/references/paper-memory.md` plus the general Atlas prompt at `modules/atlas/references/llm-fragment-prompt.md`.

The memory JSON is not a second human report. It is the agent-callable memory layer for later retrieval. It should preserve the paper's durable findings, reusable method chain, datasets/code/resources, limitations, and open questions.

Minimum requirements:

- Use the same paper slug as `output/fulltext/<paper-slug>.txt`.
- Set `note.source_type` to `pdf` when the full text came from PDF; otherwise use `other`.
- Set `note.domain` to include `科研` and `论文`; add topic labels such as `大气化学`, `卫星遥感`, `AI4Science`, `机器学习`, or `排放清单` when appropriate.
- Add `paper_profile` for fast orientation: citation key, title, authors, year, DOI, journal, research question, methods, datasets, main findings, limitations, open data, use for the user's work, and do-not-overclaim boundaries.
- Create 3-7 high-value memory fragments for full papers. Use fewer for abstract-only or paywalled papers.
- Include at least one indirect retrieval query per important fragment, so a future agent can find the paper without remembering its title.
- Keep source evidence simple: `source_evidence.path` is enough for ordinary extracted text; add `locator` only for large/nonlinear evidence such as PDF page, figure, table, supplement, or code path.

Validate each memory file before finalizing:

```bash
python modules/atlas/tools/wiki_fragment.py validate --plan output/memory/<paper-slug>.memory.json
```

Apply only when the user asks to build or update the Atlas memory index:

```bash
python modules/atlas/tools/wiki_fragment.py apply --plan output/memory/<paper-slug>.memory.json
```

## Step 6: Assemble Report

Write `output/YYYY-MM-DD_radar.md` with this structure. Use Chinese for TL;DR, `Main conclusions`, `How they proved it`, and `Limitations`; keep paper titles, links, venue names, dataset names, and code/data resource names in their original language when clearer.

```markdown
# Literature Radar - YYYY-MM-DD

> Period: DATE_FROM to DATE_TO | Candidates: N (arXiv: N, CrossRef: N) |
> Read: N full text | N abstract-only | N paywalled

---

## TL;DR

3-5 Chinese sentences max. Synthesize the signal across all papers. Do not list paper titles.

---

## Atmospheric Chemistry

### [Full Paper Title](landing_url)

**Corresponding author**: Name | Institution (| email if available)
**Published**: YYYY-MM-DD | **Venue**: Journal/Conference
**Access**: Full text | Abstract only | Paywalled

**Main conclusions**
- 中文具体结论，包含论文给出的关键数字。

**How they proved it**
- *Study type*: 中文一句话说明研究类型。
- *Data*: 数据集名称、时间、空间范围。
- *Method*: 中文详细说明从数据/假设到结论的分析链条，以及用什么诊断量证明结论。
- *Key numbers*: 支撑结论的关键数字或指标。

**Limitations**
- 中文列出论文自己承认的局限、假设、uncertainty 或 future-work caveat。

**Open data & code**
- Resource: URL or DOI *(Platform)*
- *(None stated.)*

---

## AI / ML for Science

Use the same paper block structure.

---

## Peripheral

- **[Title](landing_url)** | *Corresponding: Name, Institution* - Chinese one sentence: what it found and why it is borderline relevant.

---

## Paywalled / No OA Version

- **[Title]** | DOI: `doi` | *Journal* | Why inaccessible

---

## Stats

| Metric | N |
|--------|---|
| arXiv candidates | |
| CrossRef candidates | |
| After dedup | |
| Score-3 core | |
| Score-2 peripheral | |
| Score-1 dropped | |
| Full text read | |
| Abstract only | |
| Paywalled | |
| Papers with open data | |
```

## Quality Gate

Before finalizing:

- TL;DR synthesizes and contains no paper titles.
- Main conclusions are concrete claims, not vague "results suggest" phrasing.
- Method explains the origin-to-conclusion analysis chain and the diagnostic quantities used.
- Key numbers contain actual numbers from the paper.
- Limitations come from the paper, not inference.
- Open data/code has real URLs or DOIs, or says "None stated."
- Paywalled papers are listed instead of silently dropped.
- Corresponding author affiliation is the full institution name when available.
- Report is readable end to end in under 12 minutes.
- Every selected paper has `output/memory/<paper-slug>.memory.json`.
- Each memory JSON follows Atlas, not a paper-specific one-off schema.
