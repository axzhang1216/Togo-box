# Research Memory Routing

论文与科研记忆不是默认常驻检索层。

## Rule

- 日常聊天、项目管理、路径、脚本、个人偏好等普通对话：
  不调用论文/文献 Atlas memory。
- 只有当 query 明确涉及以下类型内容时，才进入科研记忆层：
  - 论文、文献、paper、doi、journal、abstract
  - 科研、research、study
  - 方法、模型、机制、实验、反演、数据集、观测、遥感
  - 具体科研对象，如 aerosol、ozone、SOA、GEOS-Chem、WRF、HYSPLIT

## Search Policy

打开科研记忆层后：

- 只搜索 `domain=["科研", "论文"]`
- 不扫描普通记忆层和科研记忆层的全量源文件
- 优先搜索 `retrieval_index.jsonl`
- 只有候选片段足够相关时，才进一步打开原始 note / full text

## Tool

先过门控：

```bash
python modules/atlas/tools/wiki_research_gate.py "<query>"
```

研究相关时，再执行受限检索：

```bash
python modules/atlas/tools/wiki_research_gate.py "<query>" --search
```

这条规则的目标不是提高“什么都能搜到”的概率，而是降低普通聊天时无意义触发论文检索的成本与噪声。
