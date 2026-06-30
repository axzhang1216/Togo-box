# Togo-box

Togo-box 是一个面向研究扫描的轻量 Python 工作流，目标是把“本来会闲置的 quota”变成有用的文献雷达结果。

当前默认工作流是 `literature_radar`：

1. 抓取最近的候选论文
2. 基于标题和摘要做初筛
3. 抽取可读全文或回退到摘要
4. 为后续人工精读或 LLM 深读准备结构化输入
5. 由 LLM 生成中文文献报告和 Atlas 记忆 JSON

## 当前仓库结构

```text
Togo-box/
├─ agents/
├─ modules/
│  └─ atlas/
├─ output/
├─ references/
├─ scripts/
├─ SKILL.md
└─ README.md
```

## 环境要求

- Python 3.10+

安装依赖：

```bash
python -m pip install -r requirements.txt
```

## Agent Compatibility

Togo-box is designed to be usable from both `Codex` and `Claude Code` style agent workflows.

当前兼容性结论：

- Skill 定义使用标准 `SKILL.md` + frontmatter 结构，不依赖单一 agent 私有语法
- 核心能力由 Python 脚本提供，不依赖 Codex 专属桌面 API
- Atlas 路径解析现在按仓库相对路径工作，不再绑定某一台 Windows 机器的绝对路径
- 论文、笔记、日常习惯三类记忆通过门控约定分流，避免不同 agent 在普通聊天里误扫高成本论文记忆

当前仍建议的运行前提：

- 从仓库根目录运行命令
- 使用 UTF-8 读写文件
- 如需向量检索，再额外配置 OpenAI-compatible embeddings API

## 配置

编辑 `references/config.md`：

- 把 `email` 改成你自己的邮箱
- 按研究方向调整 `atmo_keywords`、`ml_keywords`
- 需要更宽或更窄的时间窗口时修改 `days_back`

`email` 会用于：

- CrossRef polite pool
- Unpaywall 开放获取解析

## 运行流程

### 1. 抓取候选论文

```bash
python scripts/fetch_papers.py
```

输出：

- `output/candidates.json`

仅检查配置而不发网络请求：

```bash
python scripts/fetch_papers.py --dry-run
```

### 2. 自动初筛

```bash
python scripts/triage_candidates.py
```

输出：

- `output/selected.json`

该步骤会：

- 基于 `references/config.md` 中的关键词做确定性打分
- 给每篇论文附加 `score`、`track`、`matched_terms`
- 保留全部 `score=3` 的论文
- 再按 `max_selected_papers` 补入 `score=2` 的论文

### 3. 抽取全文

```bash
python scripts/extract_fulltext.py
```

输出：

- `output/fulltext/<paper-slug>.txt`
- `output/fulltext/manifest.json`

如果无法抓到可读正文，会自动回退为摘要，不会卡死在单篇论文上。

### 4. LLM 深读与 Atlas 记忆

按照 `references/research_paper_read.md` 继续执行深读。

输出：

- `output/notes.json`
- `output/YYYY-MM-DD_radar.md`
- `output/memory/<paper-slug>.memory.json`

`output/memory/*.memory.json` 使用 `modules/atlas` 的统一记忆结构。它不是另一份人类报告，而是给后续 agent 便宜、快速、准确召回用的结构化记忆。

## 当前状态

现在仓库已经具备：

- 候选论文抓取
- 自动初筛
- 全文/摘要抽取
- Atlas 记忆核心模块
- 文献阅读流程中的 Atlas memory JSON 规范

还没有完全自动化的部分：

- `notes.json` 生成
- 最终 `YYYY-MM-DD_radar.md` 报告组装
- `output/memory/*.memory.json` 的 LLM 自动生成
- 面向不同研究主题的多工作流扩展

## 开发建议

如果下一步继续开发，优先级建议是：

1. 自动生成 `notes.json`
2. 自动生成 Atlas paper memory JSON
3. 自动组装最终 Markdown 雷达报告
4. 为不同研究主题拆出独立 config/profile
