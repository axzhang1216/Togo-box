# Fragment Speech Act Types

Every piece of information in the wiki is a **Fragment** — an atomic knowledge unit classified by its speech act (what it DOES).

## The 7 Universal Speech Acts

### 1. ASSERT — 断言
**What it does:** States a fact, describes something, explains how something works.
**Signal words:** "是", "is", "使用", "contains", "has", "位于", "describes"
**Example:** "GEOS-Chem is a 3D chemical transport model"
**Example:** "MERRA-2 数据覆盖 1980-至今，空间分辨率 0.5°x0.625°"

### 2. DECIDE — 决定
**What it does:** Records a choice between alternatives, with rationale.
**Signal words:** "选择", "chose", "决定", "用A而非B", "decided to", "instead of"
**Example:** "选择 MERRA-2 而非 ERA5 作为气象驱动，因为 MERRA-2 的化学场更完整"

### 3. FIND — 发现
**What it does:** Records an observation, result, or conclusion from analysis.
**Signal words:** "发现", "found", "结果表明", "结果显示", "结论是", "conclusion"
**Example:** "发现 glyoxal 浓度在边界层最高，与观测一致"
**Example:** "CMIP6 降尺度后存在系统性暖偏差"

### 4. DO — 过程
**What it does:** Records an activity, experiment, debugging session, or workflow.
**Signal words:** "今天", "调试了", "运行了", "配置了", "debugged", "ran", "configured", step-by-step procedures
**Example:** "今天调试了 HEMCO 报错，原因是清单路径配置错误"
**Example:** "运行步骤：1) 编译 WRF 2) 设置 namelist 3) 执行"

### 5. ASK — 问题
**What it does:** Poses an open question, uncertainty, or gap in knowledge.
**Signal words:** "?", "为什么", "怎么", "是否", "why", "how", "whether", "不确定"
**Example:** "CMIP 降尺度的偏差主要来源于 GCM 还是降尺度方法？"
**Example:** "CEDS 排放清单的 VOC 物种划分是否准确？"

### 6. REMIND — 提醒
**What it does:** A task, to-do, deadline, or action item.
**Signal words:** "TODO", "待办", "记得", "注意", "deadline", "别忘了", "- [ ]"
**Example:** "TODO: 验证 CEDS VOC 排放量"
**Example:** "注意：运行前先清理 scratch 空间"

### 7. CONSTRAIN — 约束
**What it does:** A rule, limitation, requirement, or invariant that must be respected.
**Signal words:** "不能", "必须", "不应该", "cannot", "must", "should not", "限制", "要求"
**Example:** "scratch 存储不能超过 50T"
**Example:** "代码必须在提交前通过 lint 检查"

## How to Choose

Ask one question about each fragment: **"这段话在做什么？"**

- 在**描述**一个事物 → ASSERT
- 在**记录**一个选择 → DECIDE
- 在**报告**一个结果 → FIND
- 在**叙述**一个过程 → DO
- 在**提出**一个问题 → ASK
- 在**提醒**一个行动 → REMIND
- 在**规定**一个限制 → CONSTRAIN

If a paragraph does multiple things, **split it**. One fragment = one speech act.

## Fragment Output Format

Each fragment in the note gets a marker:

```
<!-- fragment: type=DECIDE tags="HEMCO,配置" links="[[geos-chem]], [[merra-2]] -->
选择社区标准清单而非自定义清单，因为更新频率高且社区验证充分。
```

The `links` field contains `[[wikilinks]]` to entity files (things, events, actors, or other statements).
