# AGENTS.md

## Project

`proofread-korean-pdf` is a cross-platform Agent Skill (compatible with Claude Code, Codex, Google Antigravity, and OpenClaw) that proofreads Korean PDF documents for spelling/grammar and fact-checks verifiable claims using parallel sub-agents, then writes Highlight and Sticky Note annotations directly onto the PDF.

## Structure

- `SKILL.md` — Skill definition and orchestration workflow followed by the agent runtime
- `scripts/extract_pdf.py` — Extracts Korean PDF text into page-tracked Markdown chunks (`<!-- PAGE: N -->`), unwrapping mid-word line breaks and creating `manifest.json` + `source_fingerprint.json`
- `scripts/run_state.py` — Resumable chunk planner and state tracker (`plan`, `record`, `status`)
- `scripts/chunk_context.py` — Prints read-only neighboring chunk excerpts (~300 chars) for boundary context
- `scripts/annotate_pdf.py` — Validates `issues_chunkNNNN.json` files, locates exact character-level bounding boxes on the PDF (even across line wraps), injects Highlight + Sticky Note annotations, and builds the Markdown summary report

## Conventions

- Keep `SKILL.md` frontmatter fields single-line (`name`, `description`, `allowed-tools`, `metadata`) for compatibility with OpenClaw, Claude Code, Codex, and Antigravity skill parsers.
- Always reference scripts via `{baseDir}/scripts/...` in `SKILL.md` — never hardcode user home paths.
- Keep sub-agent and web-search instructions in `SKILL.md` platform-neutral so Claude Code (`Agent`, `WebSearch`), Codex, Antigravity (`invoke_subagent`, `search_web`), and OpenClaw all work seamlessly.
