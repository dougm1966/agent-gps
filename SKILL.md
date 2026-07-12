---
name: agent-gps
description: Build Agent GPS maps and reports for repositories. Use when a user asks to audit, visualize, explain, diff, watch, or bridge an AI-agent working environment, including AGENTS.md/CLAUDE.md instructions, Codex/Claude/Devin agents, skills, MCP/tool configs, package scripts, related docs, and Graphify outputs.
---

# Agent GPS

Use this skill to create a standalone Agent GPS report for a repository. Agent GPS maps agentic operating context: agents, root or nested skills, skill metadata, instruction files, MCP/tool evidence, package scripts, related docs, and optional Graphify code/doc nodes.

## Workflow

1. Identify the repository root.
2. Prefer read-only inspection first. Do not modify the target repository unless the user explicitly asks.
3. Run the bundled scanner:

```powershell
python .\agent_gps.py build --root <repo-root> --out <repo-root>\agent-gps-out
```

If this skill is installed inside a Codex skills directory and you are not in the skill folder, run:

```powershell
python <skill-folder>\agent_gps.py build --root <repo-root> --out <repo-root>\agent-gps-out
```

4. Open or summarize these outputs:
   - `agent-gps.graph.json`: machine-readable graph.
   - `agent-gps.html`: standalone interactive graph.
   - `AGENT_GPS_REPORT.md`: developer-facing Agentic Structure Review.
   - `AGENT_GPS_BRIDGE.md`: Graphify bridge summary.
   - `AGENT_GPS_RECOMMENDATIONS.md`: proposed agent, skill, instruction, and routing structure.
   - `manifest.json`: source hashes for stale checks.
   - `AGENT_GPS_DIFF.md`: written by `diff`.

5. Explain results as facts, inferred links, warnings, and suggestions. Never treat inferred ownership as confirmed ownership.
6. When discussing MCPs, distinguish repo-local MCP server config from MCP tool references found in permissions, frontmatter, or tool lists.

## Commands

- `build`: generate the full graph, HTML, report, bridge report, and manifest.
- `check`: compare current agentic source hashes against the manifest.
- `diff`: write `AGENT_GPS_DIFF.md` and return nonzero when source hashes changed.
- `watch`: rebuild when detected source hashes change.
- `report`: regenerate only `AGENT_GPS_REPORT.md`.
- `bridge-graphify`: regenerate only `AGENT_GPS_BRIDGE.md`.

## Graphify Bridge

When Graphify outputs exist, Agent GPS bridges agentic surfaces to Graphify nodes by exact path mentions. Look for:

- `graphify-out/graph.json`
- `graphify-out-clean/graph.json`
- `GRAPH_REPORT.md`
- `RUN_LOG.md`

Use Graphify bridge edges as stronger evidence than free-text slug matches, but still verify ownership-critical claims in source files before making recommendations.

## MCP Reporting

Report MCP evidence in two layers:

- MCP server config: repo-local files such as `.mcp.json` or `mcp*.json` that define servers.
- MCP tool references: names such as `mcp__filesystem__read_text_file`, `mcp__playwright__browser_navigate`, or `mcp__supabase__execute_sql` found in Claude settings, agent frontmatter, or tool lists.

If tool references exist but server config does not, say that MCP tools are referenced but no repo-local server config was detected. Do not summarize that case as "no MCPs."

## Reporting Standard

When presenting results, include:

- Overall readiness grade.
- Strengths and weaknesses.
- Missing owners.
- Stale or broken references.
- Duplicated or confusing instruction surfaces.
- Agent/skill coverage.
- MCP/tool coverage.
- Whether MCP evidence is server config, tool references, or both.
- Suggested improvements ranked by value.
- Proposed agent/skill/instruction structure that can be acted on next.

For detailed output expectations, read `references/output-contract.md`.
