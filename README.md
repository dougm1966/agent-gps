# Agent GPS

Agent GPS maps the working environment that AI agents inherit when they enter a repository.

It finds agent files, skills, instruction docs, MCP/tool evidence, package scripts, related docs, referenced paths, and optional Graphify outputs. Then it generates a navigable HTML app, Markdown reports, and a machine-readable graph that show what future agents can trust, what they still have to infer, and what structure would make the repo easier to work in.

The product goal is simple: help agents do only the discovery work that is actually necessary, then leave the next agent a better map.

## Why It Exists

Modern repositories increasingly contain instructions for Codex, Claude, Cursor, Devin, Copilot, Windsurf, MCP servers, project-specific skills, and workflow docs. Those surfaces are useful, but they are often scattered. Every new agent has to rediscover:

- Which instructions apply here?
- Which agent or skill owns this kind of work?
- Which tools are allowed?
- Which paths are confirmed versus guessed?
- Which docs are reusable guidance and which are stale clues?

Agent GPS turns that working environment into a graph, a review, and an upgrade plan.

## What It Detects

- Agent surfaces: `.claude/agents/**/*.md`, `.codex/agents/*`, `.devin/agents/*`, and similar agent wrappers.
- Skill surfaces: `.agents/skills/*/SKILL.md` and `.claude/skills/*/SKILL.md`.
- Instruction docs: `AGENTS.md`, `CLAUDE.md`, Copilot instructions, Cursor rules, and Windsurf rules.
- MCP evidence: repo-local MCP server config plus MCP tool references in agent permissions and tool lists.
- Package scripts: `package.json` scripts as supporting automation context.
- Related docs: low-confidence docs whose names or contents mention agents, skills, handoffs, Graphify, Codex, Claude, and similar concepts.
- Referenced paths: existing files mentioned by agentic surfaces.
- Graphify outputs: optional code/doc graph artifacts that can bridge agent instructions to concrete code ownership.

## Quick Start

```powershell
python .\agent_gps.py build --root <repo-root> --out <repo-root>\agent-gps-out
```

Open:

```text
<repo-root>\agent-gps-out\agent-gps.html
```

The HTML app has four views:

- `Map`: visual graph with filters and clicked-node inspection.
- `Review`: readiness grade, strengths, gaps, and prioritized fixes.
- `Recommendations`: proposed agent, skill, instruction, and routing structure.
- `Reports`: embedded report summaries and an artifact inventory for the generated Markdown and JSON files.

## Commands

```powershell
python .\agent_gps.py build --root <repo-root> --out <repo-root>\agent-gps-out
python .\agent_gps.py check --root <repo-root> --out <repo-root>\agent-gps-out
python .\agent_gps.py diff --root <repo-root> --out <repo-root>\agent-gps-out
python .\agent_gps.py watch --root <repo-root> --out <repo-root>\agent-gps-out
python .\agent_gps.py report --root <repo-root> --out <repo-root>\agent-gps-out
python .\agent_gps.py bridge-graphify --root <repo-root> --out <repo-root>\agent-gps-out
```

## Outputs

- `agent-gps.html`: standalone app for navigating the map, review, recommendations, and reports.
- `agent-gps.graph.json`: machine-readable `agent-gps.v2` graph, including review and recommendations payloads.
- `AGENT_GPS_REPORT.md`: Agentic Structure Review.
- `AGENT_GPS_RECOMMENDATIONS.md`: proposed agent, skill, instruction, MCP, and routing structure.
- `AGENT_GPS_BRIDGE.md`: Graphify bridge summary.
- `manifest.json`: source hashes used by `check` and `diff`.
- `AGENT_GPS_DIFF.md`: written by `diff` when source hashes drift.

## MCP Model

Agent GPS deliberately separates two kinds of MCP evidence:

- MCP server config: repo-local files such as `.mcp.json` or `mcp*.json` that define MCP servers.
- MCP tool references: tool names such as `mcp__filesystem__read_text_file` or `mcp__supabase__execute_sql` found in Claude permissions, agent frontmatter, or tool lists.

This distinction matters. A repo can clearly show that agents are allowed to use `filesystem`, `playwright`, or `supabase` MCP tools without documenting where those MCP servers are configured. Agent GPS should credit the visible tool map while still recommending an MCP inventory when server configuration lives outside the repo.

## Certainty Controls

- `Verified`: explicit agent, skill, instruction, MCP/tool, or Graphify artifacts.
- `Supporting context`: automation/config or existing referenced paths.
- `Review first`: related docs or inferred links that should not be treated as ownership proof.
- `confirmed`: matched files, existing paths, MCP definitions/references, and Graphify artifacts.
- `inferred`: slug matches, text mentions, and relation guesses that need review.

## Readiness Grade

The grade is not a code-quality score. It is a working-environment score for AI agents.

Agent GPS rewards:

- explicit agent surfaces,
- reusable skill surfaces,
- visible MCP/tool evidence,
- Graphify bridge data,
- confirmed links over inferred links,
- clear instruction scope and precedence.

A lower grade does not mean the project is bad. It means future agents will spend more context rediscovering how to work safely.

## How This Improves Agent Work

Agent GPS is useful when it makes the next agent faster and less confused. The best output is not just a graph; it is a practical upgrade plan:

- add or consolidate agent owners,
- extract repeated guidance into skills,
- document MCP/tool availability,
- clarify instruction precedence,
- connect Graphify code/doc nodes to agentic ownership,
- promote inferred links into confirmed routing evidence.

## Skill Files

- `SKILL.md`: Codex skill instructions.
- `agents/openai.yaml`: UI metadata for the skill.
- `agent_gps.py`: standalone scanner.
- `scripts/agent_gps.py`: skill-bundled wrapper entrypoint.
- `references/output-contract.md`: detailed output expectations.
