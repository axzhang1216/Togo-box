@SKILL.md

## Claude Code Compatibility

This repository keeps the main workflow in `SKILL.md` so it can stay shared across agents.

- Run commands from the repository root.
- Prefer UTF-8 for reading and writing files.
- Treat `modules/atlas/wiki.json` paths as repository-relative, not machine-specific.
- Do not commit generated `output/` artifacts unless the task explicitly asks for them.
- For literature radar work, load `references/config.md` first and then follow `references/research_paper_read.md`.

## Claude Code Usage

- Project instructions come from this file.
- Skill-style invocation is available at `.claude/skills/togo-box/SKILL.md`.
- Atlas remains an internal module; use `modules/atlas/tools/wiki_gate.py` when retrieval routing matters.
