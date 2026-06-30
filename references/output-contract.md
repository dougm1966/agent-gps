# Agent GPS Output Contract

Agent GPS should help a developer understand how AI agents and automation are expected to work in a repository.

## Node Details

Each meaningful node should expose:

- What it is.
- Exact file path, when applicable.
- Why it was included.
- Confidence explanation.
- First useful excerpt or summary.
- Connected nodes grouped by relation.
- Confirmed facts and inferred links separated.
- Recommended read-next files.

## Graph Clarity

Use distinct node kinds for:

- Agents.
- Skills.
- Instruction docs.
- MCP server configs.
- MCP tool permission configs.
- MCP/tool references.
- Package scripts.
- Related docs.
- Referenced code paths.
- Graphify code/doc nodes.

## MCP Evidence

MCP evidence must not be flattened into a single yes/no claim.

- MCP server config means Agent GPS found repo-local server definitions such as `.mcp.json` or `mcp*.json`.
- MCP tool references mean Agent GPS found allowed or mentioned tool names such as `mcp__filesystem__read_text_file`.
- If tool references exist without server config, report that MCP tools are visible but the server source is not documented in the repo.
- If neither server config nor tool references exist, then it is accurate to say no MCP/tool evidence was detected.

## Certainty Controls

- Verified nodes: matched source files, explicit agent/skill/instruction surfaces, MCP definitions/references, and Graphify artifacts.
- Supporting context nodes: existing referenced paths, package scripts, and supporting config.
- Review first nodes: related docs or inferred matches that should not be treated as ownership proof.
- Confirmed facts: matched files, existing paths, MCP definitions/references, and Graphify artifacts.
- Inferred links: slug matches, plain text mentions, and tool-name mentions.
- Warnings: stale-looking docs, ambiguous ownership, missing configs, or broken references.
- Suggestions: ranked improvements that would make agentic operation clearer.

## Recommendations

`AGENT_GPS_RECOMMENDATIONS.md` should translate diagnosis into action:

- Proposed agents seeded from existing agent/instruction surfaces.
- Proposed skills seeded from reusable workflow guidance.
- Instruction cleanup for precedence, duplication, and tool availability.
- MCP inventory guidance when MCP tools are referenced but server configuration is external or undocumented.
- A routing table that maps code/doc paths to recommended owner/context.
- Next artifacts the user or next agent can create.
