# Gating Conventions

Atlas 不是“所有记忆默认全查”的系统。

它的默认原则是：

- 让真正常用、低成本、强个性化的记忆常驻前台
- 让高体量、高噪声、强主题性的记忆按需打开
- 让不同来源的 memory 支持不同门控约定，而不是只靠 `domain` 标签硬过滤

## 当前三种约定

### 1. 日常习惯约定

- 作用对象：
  聊天整理出的代码习惯、兴趣方向、常见纠错点、对 agent 的长期偏好
- 行为：
  永远属于前台记忆，可默认参与检索

### 2. 论文门控约定

- 作用对象：
  论文、文献、paper notes、paper memory JSON
- 行为：
  普通聊天不查
  只有在 query 明确涉及科研、论文、文献、方法、模型、实验、数据集、观测、遥感等语境时才查

### 3. 笔记门控约定

- 作用对象：
  旧的 md 笔记、讨论记录、日常信息、聊天摘录
- 行为：
  只有当用户明确需要“回忆”“追溯”“复盘”“你还记得”“我们之前讨论过”这类操作时才查

## Config

配置文件：

`modules/atlas/gating_conventions.json`

## Tool

统一门控入口：

```bash
python modules/atlas/tools/wiki_gate.py "<query>"
python modules/atlas/tools/wiki_gate.py "<query>" --search
```

它会：

1. 识别当前 query 激活了哪些约定
2. 只在激活约定的过滤空间中检索
3. 合并结果，而不是把所有 memory 层混在一起扫
