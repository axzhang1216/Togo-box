---
name: togo-box
description: >
  Cross-agent entrypoint for quota-burning literature radar, paper reading, and Atlas memory generation
  inside Claude Code.
---

# Togo-box

Use this skill when the user wants to scan papers, read selected full text, assemble a concise research briefing, or convert materials into Atlas memory artifacts.

## Load Order

1. Read `../../../SKILL.md` for the shared Togo-box contract.
2. Read `../../../references/config.md` for topic and source settings.
3. Read `../../../references/research_paper_read.md` for the active workflow.

## Claude Code Notes

- Run commands from the repository root so relative paths stay valid.
- Prefer the bundled Python scripts over reimplementing the workflow in chat.
- Keep Atlas retrieval gated: ordinary chat should not open paper memory unless the request is research- or literature-related.
