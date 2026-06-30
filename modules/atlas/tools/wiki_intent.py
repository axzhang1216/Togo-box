#!/usr/bin/env python3
"""
wiki_intent.py — Intent classifier for natural language wiki operations.

Classifies user input into structured operation payloads that wiki_writer.py
can execute deterministically.

Usage:
  python wiki_intent.py classify "把这篇论文加到wiki里" --source "path/to/file"
  python wiki_intent.py classify "GEOS-Chem那个配置改了什么"

Output: JSON operation payload(s)
"""

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Entity type detection keywords
# ---------------------------------------------------------------------------

ENTITY_KEYWORDS = {
    "projects": [
        "项目", "课题", "研究方向", "project", "research direction", "启动", "立项",
    ],
    "papers": [
        "论文", "paper", "文献", "文章", "发表", "投稿", "arxiv", "doi",
        "journal", "ACP", "JGR", "GRL", "ES&T",
    ],
    "methods": [
        "方法", "算法", "技术", "method", "approach", "technique", "model",
        "模拟", "反演", "inversion", "emission",
    ],
    "datasets": [
        "数据", "数据集", "dataset", "数据产品", "再分析", "reanalysis",
        "MERRA", "ERA5", "CMIP", "GEOS", "satellite", "卫星",
    ],
    "code": [
        "代码", "工具", "脚本", "code", "tool", "script", "repository", "repo",
        "GEOS-Chem", "WRF", "WRF-GC", "HEMCO", "Python", "Fortran",
    ],
    "decisions": [
        "决定", "选择", "方案", "decision", "choose", "选", "用A还是B",
        "方案对比", "trade-off",
    ],
    "configs": [
        "配置", "设置", "config", "configuration", "setup", "参数",
        "run文件", "input file", "HEMCO", "geoschem_config",
    ],
    "people": [
        "人", "教授", "老师", "合作者", "person", "PI", "导师", "postdoc",
        "researcher", "教授",
    ],
    "meetings": [
        "会议", "组会", "讨论", "meeting", "seminar", "conference", "workshop",
        "poster", "报告", "汇报",
    ],
}

# Operation keywords
OP_KEYWORDS = {
    "create": [
        "添加", "新建", "创建", "add", "create", "new", "记一下",
        "记录", "保存", "把这个", "这篇论文", "这个方法", "这个数据",
    ],
    "update": [
        "更新", "修改", "改", "update", "edit", "修改为", "改为",
        "变更", "调整",
    ],
    "link": [
        "关联", "联系", "link", "relate", "属于", "来自", "基于",
        "用了", "使用了", "引用了",
    ],
    "status": [
        "完成", "暂停", "放弃", "激活", "完成度", "done", "paused",
        "cancelled", "active", "completed",
    ],
    "query": [
        "查", "找", "搜索", "什么", "哪些", "怎么", "为什么",
        "search", "find", "what", "how", "why", "query",
    ],
}


def detect_entity_type(text: str) -> Optional[str]:
    """Detect the most likely entity type from text."""
    text_lower = text.lower()
    scores: Dict[str, int] = {}

    for etype, keywords in ENTITY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[etype] = score

    if not scores:
        return None
    return max(scores, key=scores.get)


def detect_operation(text: str) -> str:
    """Detect the intended operation from text."""
    text_lower = text.lower()
    scores: Dict[str, int] = {}

    for op, keywords in OP_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text_lower)
        if score > 0:
            scores[op] = score

    if not scores:
        # If there's a question mark or question words, it's likely a query
        if re.search(r"[?？]|什么|哪些|怎么|为什么|how|what|why", text_lower):
            return "query"
        # Default to create if there's substantive content
        return "create"

    return max(scores, key=scores.get)


def extract_title_hint(text: str) -> Optional[str]:
    """Try to extract a title/entity name from the text."""
    # Common patterns: "把X加到wiki", "X的配置", "关于X的决定"
    patterns = [
        r"把(.+?)加[到入]",
        r"(.+?)的(?:配置|决定|方法|数据|代码|论文)",
        r"关于(.+?)(?:的|$)",
        r"(?:记录|保存|记一下)\s*(.+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()
    return None


def classify(text: str, source: Optional[str] = None) -> Dict[str, Any]:
    """Classify natural language input into an operation payload."""
    entity_type = detect_entity_type(text)
    operation = detect_operation(text)
    title_hint = extract_title_hint(text)

    payload: Dict[str, Any] = {
        "operation": operation,
        "entity_type": entity_type,
        "title_hint": title_hint,
        "source": source,
        "raw_text": text,
    }

    # For create operations with a source file, we need the LLM to extract
    # structured fields — the intent classifier just identifies WHAT to do
    if operation == "create" and source:
        payload["needs_extraction"] = True
        payload["extraction_prompt"] = (
            f"Read the source file and extract structured fields for a {entity_type} entity. "
            f"Use the template at the template_dir for field definitions."
        )

    # For query operations, route to wiki-search
    if operation == "query":
        payload["search_query"] = title_hint or text

    return payload


def main():
    parser = argparse.ArgumentParser(description="Classify natural language into wiki operations")
    parser.add_argument("text", help="Natural language input to classify")
    parser.add_argument("--source", default=None, help="Source file path (if ingesting)")
    args = parser.parse_args()

    result = classify(args.text, args.source)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
