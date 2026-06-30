from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


IGNORE_DIRS = {
    ".git",
    ".next",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "out",
}

HIGH_CONFIDENCE = "high"
MEDIUM_CONFIDENCE = "medium"
LOW_CONFIDENCE = "low"

GRAPHIFY_OUTPUTS = [
    "graphify-out/graph.json",
    "graphify-out-clean/graph.json",
]

GRAPHIFY_REPORTS = [
    "GRAPH_REPORT.md",
    "RUN_LOG.md",
]

KIND_LABELS = {
    "project": "Project",
    "surface": "Surface group",
    "claude_agent": "Claude agent",
    "claude_skill": "Claude skill mirror",
    "canonical_skill": "Canonical skill",
    "codex_agent": "Codex agent",
    "devin_agent": "Devin agent",
    "instruction_doc": "Instruction doc",
    "copilot_instruction": "Copilot instruction",
    "cursor_rule": "Cursor rule",
    "windsurf_rule": "Windsurf rule",
    "mcp_config": "MCP config",
    "tool_permission_config": "Tool permission config",
    "mcp_tool": "MCP/tool",
    "package_scripts": "Package scripts",
    "related_doc": "Related doc",
    "referenced_file": "Referenced file",
    "graphify_code": "Graphify code node",
    "graphify_doc": "Graphify doc node",
    "graphify_node": "Graphify node",
    "graphify_report": "Graphify report",
}

CONFIDENCE_EXPLANATIONS = {
    HIGH_CONFIDENCE: "high-confidence because Agent GPS matched an explicit agent, skill, instruction, tool, or Graphify output.",
    MEDIUM_CONFIDENCE: "medium-confidence because Agent GPS matched supporting automation/config or an existing referenced path.",
    LOW_CONFIDENCE: "low-confidence because Agent GPS found related language or naming that should be reviewed by a human.",
}


@dataclass(frozen=True)
class SurfaceRule:
    kind: str
    confidence: str
    pattern: str
    label: str


SURFACE_RULES = [
    SurfaceRule("claude_agent", HIGH_CONFIDENCE, ".claude/agents/*/AGENT.md", "Claude agents"),
    SurfaceRule("claude_agent", HIGH_CONFIDENCE, ".claude/agents/*.md", "Claude agents"),
    SurfaceRule("claude_agent", HIGH_CONFIDENCE, ".claude/agents/**/*.md", "Claude agents"),
    SurfaceRule("claude_skill", HIGH_CONFIDENCE, ".claude/skills/*/SKILL.md", "Claude skill mirrors"),
    SurfaceRule("canonical_skill", HIGH_CONFIDENCE, ".agents/skills/*/SKILL.md", "Canonical skills"),
    SurfaceRule("codex_agent", HIGH_CONFIDENCE, ".codex/agents/*.toml", "Codex agent wrappers"),
    SurfaceRule("codex_agent", HIGH_CONFIDENCE, ".codex/agents/*/AGENT.md", "Codex agents"),
    SurfaceRule("devin_agent", HIGH_CONFIDENCE, ".devin/agents/*/AGENT.md", "Devin agent wrappers"),
    SurfaceRule("instruction_doc", HIGH_CONFIDENCE, "AGENTS.md", "Root agent instructions"),
    SurfaceRule("instruction_doc", HIGH_CONFIDENCE, "**/AGENTS.md", "Agent instructions"),
    SurfaceRule("instruction_doc", HIGH_CONFIDENCE, "CLAUDE.md", "Claude instructions"),
    SurfaceRule("instruction_doc", HIGH_CONFIDENCE, "**/CLAUDE.md", "Claude instructions"),
    SurfaceRule("copilot_instruction", HIGH_CONFIDENCE, ".github/copilot-instructions.md", "Copilot instructions"),
    SurfaceRule("cursor_rule", HIGH_CONFIDENCE, ".cursor/rules/**/*", "Cursor rules"),
    SurfaceRule("cursor_rule", HIGH_CONFIDENCE, ".cursorrules", "Cursor rules"),
    SurfaceRule("windsurf_rule", HIGH_CONFIDENCE, ".windsurf/rules/**/*", "Windsurf rules"),
    SurfaceRule("mcp_config", MEDIUM_CONFIDENCE, ".mcp.json", "MCP config"),
    SurfaceRule("mcp_config", MEDIUM_CONFIDENCE, "**/mcp*.json", "MCP config"),
    SurfaceRule("tool_permission_config", MEDIUM_CONFIDENCE, ".claude/settings.json", "Claude tool permissions"),
    SurfaceRule("tool_permission_config", MEDIUM_CONFIDENCE, ".claude/settings.local.json", "Claude tool permissions"),
    SurfaceRule("package_scripts", MEDIUM_CONFIDENCE, "package.json", "Package scripts"),
]

LOW_CONFIDENCE_NAME_RE = re.compile(
    r"(agent|agents|skill|skills|handoff|gps|graphify|codex|claude|copilot|cursor|devin)",
    re.I,
)

PATH_RE = re.compile(r"`([^`]+)`|(?:^|[\s(])((?:\.?[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.@/-]+\.[A-Za-z0-9]+)")
MCP_TOOL_RE = re.compile(r"\bmcp__([A-Za-z0-9_-]+)__([A-Za-z0-9_-]+)\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_posix(path: Path) -> str:
    return path.as_posix()


def rel(root: Path, path: Path) -> str:
    return to_posix(path.relative_to(root))


def is_ignored(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"---\s*\n(.*?)\n---\s*\n?(.*)", text, re.S)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("'\"")
    return meta, match.group(2)


def first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def compact_text(value: str, limit: int = 420) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


def useful_excerpt(description: str, body: str) -> str:
    if description:
        return compact_text(description)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("---"):
            continue
        if stripped.startswith("|") or stripped.startswith("```"):
            continue
        return compact_text(stripped)
    return ""


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind.replace("_", " ").title())


def confidence_explanation(confidence: str) -> str:
    return CONFIDENCE_EXPLANATIONS.get(confidence, f"{confidence.title()} confidence.")


def source_inclusion_reason(source: dict) -> str:
    return f"Matched {source['surface']} as `{source['kind']}` at `{source['path']}`."


def slug_from_path(path: Path, kind: str) -> str:
    if kind in {"claude_agent", "devin_agent", "claude_skill", "canonical_skill", "codex_agent"}:
        if path.name in {"AGENT.md", "SKILL.md"}:
            return path.parent.name
        return path.stem
    return path.stem or path.name


def find_paths(root: Path, pattern: str) -> list[Path]:
    paths = []
    for path in root.glob(pattern):
        if not path.is_file() or is_ignored(path.relative_to(root)):
            continue
        paths.append(path)
    return paths


def stable_node_id(kind: str, path_rel: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", path_rel).strip("-").lower()
    return f"{kind}:{clean}"


def stable_simple_id(kind: str, value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return f"{kind}:{clean}"


def add_node(nodes: dict[str, dict], node_id: str, **attrs: object) -> None:
    node = nodes.setdefault(node_id, {"id": node_id})
    node.update(attrs)


def add_edge(edges: list[dict], source: str, target: str, relation: str, **attrs: object) -> None:
    if source == target:
        return
    edge = {"source": source, "target": target, "relation": relation, "classification": attrs.pop("classification", "confirmed")}
    edge.update(attrs)
    for existing in edges:
        if (
            existing.get("source") == edge["source"]
            and existing.get("target") == edge["target"]
            and existing.get("relation") == edge["relation"]
            and existing.get("classification") == edge["classification"]
        ):
            return
    edges.append(edge)


def detect_sources(root: Path) -> list[dict]:
    by_path: dict[str, dict] = {}

    for rule in SURFACE_RULES:
        for path in find_paths(root, rule.pattern):
            path_rel = rel(root, path)
            current = by_path.get(path_rel)
            if current and current["confidence"] == HIGH_CONFIDENCE:
                continue
            text = read_text(path)
            meta, body = parse_frontmatter(text)
            slug = slug_from_path(path, rule.kind)
            description = meta.get("description", "")
            by_path[path_rel] = {
                "path": path_rel,
                "kind": rule.kind,
                "surface": rule.label,
                "confidence": rule.confidence,
                "slug": meta.get("name", slug),
                "description": description,
                "heading": first_heading(body),
                "excerpt": useful_excerpt(description, body),
                "inclusion_reason": f"Matched {rule.label} via `{rule.pattern}`.",
                "hash": sha256_file(path),
                "size": path.stat().st_size,
            }

    docs_root = root / "docs"
    if docs_root.exists():
        for path in docs_root.rglob("*.md"):
            if not path.is_file() or is_ignored(path.relative_to(root)):
                continue
            path_rel = rel(root, path)
            if path_rel in by_path:
                continue
            if not LOW_CONFIDENCE_NAME_RE.search(path.name):
                text_sample = read_text(path)[:4000]
                if not LOW_CONFIDENCE_NAME_RE.search(text_sample):
                    continue
            text = read_text(path)
            _, body = parse_frontmatter(text)
            by_path[path_rel] = {
                "path": path_rel,
                "kind": "related_doc",
                "surface": "Related docs",
                "confidence": LOW_CONFIDENCE,
                "slug": path.stem,
                "description": "",
                "heading": first_heading(body),
                "excerpt": useful_excerpt("", body),
                "inclusion_reason": "Matched related documentation by filename or content mentioning agentic surfaces.",
                "hash": sha256_file(path),
                "size": path.stat().st_size,
            }

    return sorted(by_path.values(), key=lambda item: item["path"])


def extract_path_mentions(text: str) -> list[str]:
    mentions: set[str] = set()
    for match in PATH_RE.finditer(text):
        value = match.group(1) or match.group(2)
        if not value:
            continue
        value = value.strip().strip(".,);")
        if "/" in value and not value.startswith("http"):
            mentions.add(value)
    return sorted(mentions)


def load_json(path: Path) -> object | None:
    try:
        return json.loads(read_text(path))
    except (OSError, json.JSONDecodeError):
        return None


def extract_mcp_tools(root: Path, sources: list[dict]) -> dict[str, list[dict]]:
    tools_by_config: dict[str, list[dict]] = {}
    for source in sources:
        if source["kind"] != "mcp_config":
            continue
        data = load_json(root / source["path"])
        tools: list[dict] = []
        if isinstance(data, dict):
            servers = data.get("mcpServers") or data.get("servers") or {}
            if isinstance(servers, dict):
                for name, config in servers.items():
                    command = ""
                    if isinstance(config, dict):
                        command = str(config.get("command", ""))
                    tools.append({"name": str(name), "command": command, "source_path": source["path"]})
        tools_by_config[source["path"]] = sorted(tools, key=lambda item: item["name"].lower())
    return tools_by_config


def extract_mcp_tool_references(text: str, source_path: str) -> list[dict[str, str]]:
    refs: dict[tuple[str, str], dict[str, str]] = {}
    for match in MCP_TOOL_RE.finditer(text):
        server = match.group(1)
        tool = match.group(2)
        refs[(server.lower(), tool.lower())] = {
            "server": server,
            "tool": tool,
            "source_path": source_path,
        }
    return sorted(refs.values(), key=lambda item: (item["server"].lower(), item["tool"].lower()))


def classify_graphify_kind(kind: str, path: str) -> str:
    value = f"{kind} {path}".lower()
    if "doc" in value or path.endswith((".md", ".mdx", ".txt")):
        return "graphify_doc"
    if path:
        return "graphify_code"
    return "graphify_node"


def load_graphify_nodes(root: Path) -> list[dict]:
    nodes: dict[str, dict] = {}
    for output in GRAPHIFY_OUTPUTS:
        path = root / output
        if not path.exists():
            continue
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        raw_nodes = data.get("nodes", [])
        if not isinstance(raw_nodes, list):
            continue
        for item in raw_nodes:
            if not isinstance(item, dict):
                continue
            node_path = str(item.get("path") or item.get("file") or item.get("id") or "")
            node_path = node_path.replace("\\", "/")
            if node_path.startswith("code:"):
                node_path = node_path[5:]
            node_kind = classify_graphify_kind(str(item.get("kind", "")), node_path)
            node_id = stable_node_id(node_kind, node_path or str(item.get("id", "")))
            nodes[node_id] = {
                "id": node_id,
                "kind": node_kind,
                "label": str(item.get("label") or Path(node_path).name or item.get("id") or "Graphify node"),
                "path": node_path,
                "confidence": HIGH_CONFIDENCE,
                "description": f"Imported from {output}.",
                "what": kind_label(node_kind),
                "inclusion_reason": f"Graphify output `{output}` contained this node.",
                "confidence_explanation": confidence_explanation(HIGH_CONFIDENCE),
                "excerpt": str(item.get("summary") or item.get("description") or ""),
                "confirmed_facts": [f"Present in `{output}`.", f"Path: `{node_path}`." if node_path else "Graphify node has no path."],
                "inferred_links": [],
                "warnings": [],
                "suggestions": [],
                "read_next": [],
                "connections_by_relation": {},
            }
    for report in GRAPHIFY_REPORTS:
        path = root / report
        if not path.exists() or not path.is_file():
            continue
        node_id = stable_node_id("graphify_report", report)
        nodes[node_id] = {
            "id": node_id,
            "kind": "graphify_report",
            "label": report,
            "path": report,
            "confidence": HIGH_CONFIDENCE,
            "description": "Graphify report artifact detected.",
            "what": kind_label("graphify_report"),
            "inclusion_reason": f"Found Graphify report `{report}`.",
            "confidence_explanation": confidence_explanation(HIGH_CONFIDENCE),
            "excerpt": compact_text(read_text(path), 360),
            "confirmed_facts": [f"Found `{report}`."],
            "inferred_links": [],
            "warnings": [],
            "suggestions": [],
            "read_next": [],
            "connections_by_relation": {},
        }
    return sorted(nodes.values(), key=lambda item: item["id"])


def source_mentions_tool(text: str, tool_name: str) -> bool:
    clean = re.escape(tool_name.lower())
    return re.search(rf"\b{clean}\b", text.lower()) is not None


def add_node_details(nodes: dict[str, dict], edges: list[dict]) -> None:
    by_id = nodes
    outgoing: dict[str, list[dict]] = {}
    incoming: dict[str, list[dict]] = {}
    for edge in edges:
        outgoing.setdefault(edge["source"], []).append(edge)
        incoming.setdefault(edge["target"], []).append(edge)

    for node_id, node in by_id.items():
        node.setdefault("what", kind_label(str(node.get("kind", ""))))
        node.setdefault("inclusion_reason", "Included as part of the Agent GPS project map.")
        node.setdefault("confidence_explanation", confidence_explanation(str(node.get("confidence", MEDIUM_CONFIDENCE))))
        node.setdefault("excerpt", node.get("description", ""))

        groups: dict[str, list[dict]] = {}
        confirmed: list[str] = []
        inferred: list[str] = []
        read_next: list[str] = []
        for edge in outgoing.get(node_id, []) + incoming.get(node_id, []):
            other_id = edge["target"] if edge["source"] == node_id else edge["source"]
            other = by_id.get(other_id, {"id": other_id})
            relation = str(edge["relation"])
            entry = {
                "id": other_id,
                "label": other.get("label") or other.get("path") or other_id,
                "path": other.get("path", ""),
                "direction": "outgoing" if edge["source"] == node_id else "incoming",
                "classification": edge.get("classification", "confirmed"),
            }
            groups.setdefault(relation, []).append(entry)
            label = str(entry["label"])
            if edge.get("classification") == "inferred":
                inferred.append(f"{relation}: {label}")
            else:
                confirmed.append(f"{relation}: {label}")
            other_path = str(other.get("path") or "")
            if other_path and other_path not in read_next and other_path != node.get("path"):
                read_next.append(other_path)

        node["connections_by_relation"] = {key: value for key, value in sorted(groups.items())}
        node["confirmed_facts"] = node.get("confirmed_facts") or confirmed[:8]
        node["inferred_links"] = node.get("inferred_links") or inferred[:8]
        node["warnings"] = node.get("warnings") or []
        node["suggestions"] = node.get("suggestions") or []
        node["read_next"] = node.get("read_next") or read_next[:6]


def build_graph(root: Path) -> dict:
    sources = detect_sources(root)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    mcp_tools_by_config = extract_mcp_tools(root, sources)
    graphify_nodes = load_graphify_nodes(root)

    add_node(
        nodes,
        "project:root",
        kind="project",
        label=root.name,
        path=".",
        confidence=HIGH_CONFIDENCE,
        what="Project",
        inclusion_reason="Repository root passed to Agent GPS.",
        confidence_explanation=confidence_explanation(HIGH_CONFIDENCE),
        excerpt=f"Agentic structure map for {root.name}.",
    )

    surface_ids: dict[str, str] = {}
    source_nodes: dict[str, str] = {}
    slug_index: dict[str, list[str]] = {}

    for source in sources:
        surface_id = f"surface:{re.sub(r'[^a-z0-9]+', '-', source['surface'].lower()).strip('-')}"
        surface_ids[source["surface"]] = surface_id
        add_node(
            nodes,
            surface_id,
            kind="surface",
            label=source["surface"],
            confidence=source["confidence"],
            what="Surface group",
            inclusion_reason=f"One or more files matched the {source['surface']} surface.",
            confidence_explanation=confidence_explanation(source["confidence"]),
            excerpt=f"Groups {source['surface']} nodes.",
        )
        add_edge(edges, "project:root", surface_id, "has_surface")

        node_id = stable_node_id(source["kind"], source["path"])
        source_nodes[source["path"]] = node_id
        label = source["heading"] or source["slug"] or source["path"]
        add_node(
            nodes,
            node_id,
            kind=source["kind"],
            label=label,
            path=source["path"],
            confidence=source["confidence"],
            description=source["description"],
            what=kind_label(source["kind"]),
            inclusion_reason=source["inclusion_reason"],
            confidence_explanation=confidence_explanation(source["confidence"]),
            excerpt=source.get("excerpt", ""),
            confirmed_facts=[source_inclusion_reason(source), f"File hash: `{source['hash']}`."],
            inferred_links=[],
            warnings=[],
            suggestions=[],
            read_next=[],
            hash=source["hash"],
            size=source["size"],
        )
        add_edge(edges, surface_id, node_id, "contains")
        slug_index.setdefault(str(source["slug"]).lower(), []).append(node_id)

    tool_nodes: dict[str, str] = {}
    tool_ref_counts: Counter[str] = Counter()
    tool_ref_examples: dict[str, list[str]] = {}
    for config_path, tools in mcp_tools_by_config.items():
        config_id = source_nodes.get(config_path)
        for tool in tools:
            tool_id = stable_simple_id("mcp_tool", tool["name"])
            tool_nodes[tool["name"].lower()] = tool_id
            add_node(
                nodes,
                tool_id,
                kind="mcp_tool",
                label=tool["name"],
                path=config_path,
                confidence=HIGH_CONFIDENCE,
                description=f"MCP/tool server defined in {config_path}.",
                what=kind_label("mcp_tool"),
                inclusion_reason=f"`{config_path}` defines MCP server `{tool['name']}`.",
                confidence_explanation=confidence_explanation(HIGH_CONFIDENCE),
                excerpt=tool.get("command", ""),
                confirmed_facts=[f"Defined in `{config_path}`."],
                inferred_links=[],
                warnings=[],
                suggestions=[],
                read_next=[config_path],
            )
            if config_id:
                add_edge(edges, config_id, tool_id, "defines_tool", classification="confirmed")

    for source in sources:
        source_path = root / source["path"]
        text = read_text(source_path)
        source_id = source_nodes[source["path"]]
        for ref in extract_mcp_tool_references(text, source["path"]):
            server_key = ref["server"].lower()
            tool_ref_counts[server_key] += 1
            tool_ref_examples.setdefault(server_key, [])
            if ref["tool"] not in tool_ref_examples[server_key]:
                tool_ref_examples[server_key].append(ref["tool"])
            tool_id = stable_simple_id("mcp_tool", ref["server"])
            tool_nodes[server_key] = tool_id
            add_node(
                nodes,
                tool_id,
                kind="mcp_tool",
                label=ref["server"],
                path=source["path"],
                confidence=HIGH_CONFIDENCE if source["kind"] == "tool_permission_config" else MEDIUM_CONFIDENCE,
                description=f"MCP server/tool references found in {source['path']}.",
                what=kind_label("mcp_tool"),
                inclusion_reason=f"`{source['path']}` references MCP server `{ref['server']}`.",
                confidence_explanation=confidence_explanation(HIGH_CONFIDENCE if source["kind"] == "tool_permission_config" else MEDIUM_CONFIDENCE),
                excerpt=", ".join(tool_ref_examples[server_key][:6]),
                confirmed_facts=[f"Referenced by `{source['path']}`.", f"Example tool: `{ref['tool']}`."],
                inferred_links=[],
                warnings=[],
                suggestions=[],
                read_next=[source["path"]],
            )
            add_edge(edges, source_id, tool_id, "allows_tool" if source["kind"] == "tool_permission_config" else "mentions_tool", classification="confirmed")

    graphify_by_path: dict[str, str] = {}
    for graphify_node in graphify_nodes:
        node_id = graphify_node["id"]
        add_node(nodes, node_id, **graphify_node)
        path = str(graphify_node.get("path") or "")
        if path:
            graphify_by_path[path.strip("/")] = node_id
        add_edge(edges, "project:root", node_id, "has_graphify_node", classification="confirmed")

    source_paths = set(source_nodes)
    for source in sources:
        source_path = root / source["path"]
        text = read_text(source_path)
        source_id = source_nodes[source["path"]]

        for mention in extract_path_mentions(text):
            cleaned = mention.strip("/")
            if cleaned in source_paths:
                add_edge(edges, source_id, source_nodes[cleaned], "mentions_file")
            elif (root / cleaned).exists():
                node_id = stable_node_id("referenced_file", cleaned)
                add_node(
                    nodes,
                    node_id,
                    kind="referenced_file",
                    label=Path(cleaned).name,
                    path=cleaned,
                    confidence=MEDIUM_CONFIDENCE,
                    what=kind_label("referenced_file"),
                    inclusion_reason=f"`{source['path']}` mentions existing path `{cleaned}`.",
                    confidence_explanation=confidence_explanation(MEDIUM_CONFIDENCE),
                    excerpt="",
                )
                add_edge(edges, source_id, node_id, "mentions_path", classification="confirmed")
            if cleaned in graphify_by_path:
                add_edge(edges, source_id, graphify_by_path[cleaned], "bridges_to_graphify", classification="confirmed")

        lower = text.lower()
        for slug, ids in slug_index.items():
            if len(slug) < 3:
                continue
            if re.search(rf"\b{re.escape(slug)}\b", lower):
                for target_id in ids:
                    if target_id != source_id:
                        add_edge(edges, source_id, target_id, "mentions_surface", classification="inferred")

        for tool_name, tool_id in tool_nodes.items():
            if source["kind"] != "mcp_config" and source_mentions_tool(text, tool_name):
                add_edge(edges, source_id, tool_id, "mentions_tool", classification="inferred")

    canonical_agents = [s for s in sources if s["kind"] == "claude_agent"]
    canonical_skills = [s for s in sources if s["kind"] == "canonical_skill"]
    agent_surfaces = [s for s in sources if s["kind"] in {"claude_agent", "codex_agent", "devin_agent"}]
    skill_surfaces = [s for s in sources if s["kind"] in {"canonical_skill", "claude_skill"}]
    wrappers = [s for s in sources if s["kind"] in {"codex_agent", "devin_agent", "claude_skill"}]
    canonical_by_slug = {Path(s["path"]).parent.name.lower() if s["path"].endswith(("AGENT.md", "SKILL.md")) else Path(s["path"]).stem.lower(): s for s in canonical_agents + canonical_skills}

    for wrapper in wrappers:
        wrapper_slug = Path(wrapper["path"]).parent.name.lower() if wrapper["path"].endswith(("AGENT.md", "SKILL.md")) else Path(wrapper["path"]).stem.lower()
        canonical = canonical_by_slug.get(wrapper_slug)
        if canonical:
            add_edge(edges, source_nodes[wrapper["path"]], source_nodes[canonical["path"]], "generated_from")

    graphify_sources: dict[str, list[str]] = {}
    for edge in edges:
        if edge["relation"] == "bridges_to_graphify":
            graphify_sources.setdefault(edge["target"], []).append(edge["source"])
    for source_ids in graphify_sources.values():
        for index, source_id in enumerate(source_ids):
            for target_id in source_ids[index + 1 :]:
                add_edge(edges, source_id, target_id, "shares_graphify_target", classification="inferred")
                add_edge(edges, target_id, source_id, "shares_graphify_target", classification="inferred")

    add_node_details(nodes, edges)
    relation_counts = Counter(edge["relation"] for edge in edges)
    kind_counts = Counter(node["kind"] for node in nodes.values())
    confidence_counts = Counter(source["confidence"] for source in sources)
    edge_classification_counts = Counter(edge.get("classification", "confirmed") for edge in edges)

    graph_payload = {
        "schema": "agent-gps.v2",
        "generated_at": utc_now(),
        "root": str(root),
        "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
        "edges": sorted(edges, key=lambda item: (item["source"], item["relation"], item["target"])),
        "sources": sources,
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "sources": len(sources),
            "canonical_agents": len(canonical_agents),
            "canonical_skills": len(canonical_skills),
            "agent_surfaces": len(agent_surfaces),
            "skill_surfaces": len(skill_surfaces),
            "mcp_server_configs": sum(1 for source in sources if source["kind"] == "mcp_config"),
            "mcp_tool_references": sum(tool_ref_counts.values()),
            "mcp_tools": len(tool_nodes),
            "graphify_nodes": len(graphify_nodes),
            "node_kinds": dict(sorted(kind_counts.items())),
            "edge_relations": dict(sorted(relation_counts.items())),
            "edge_classifications": dict(sorted(edge_classification_counts.items())),
            "confidence": dict(sorted(confidence_counts.items())),
        },
    }
    graph_payload["review"] = build_quality_review(graph_payload)
    graph_payload["recommendations"] = build_recommendations(graph_payload)
    return graph_payload


def write_report(out: Path, graph: dict) -> None:
    summary = graph["summary"]
    review = build_quality_review(graph)
    lines = [
        "# Agent GPS Report",
        "",
        f"Generated: {graph['generated_at']}",
        f"Root: `{graph['root']}`",
        "",
        "## Summary",
        "",
        f"- Sources: {summary['sources']}",
        f"- Nodes: {summary['nodes']}",
        f"- Edges: {summary['edges']}",
        f"- Agent surfaces: {summary.get('agent_surfaces', summary['canonical_agents'])}",
        f"- Skill surfaces: {summary.get('skill_surfaces', summary['canonical_skills'])}",
        f"- Canonical agents: {summary['canonical_agents']}",
        f"- Canonical skills: {summary['canonical_skills']}",
        f"- MCP/tools: {summary.get('mcp_tools', 0)}",
        f"- MCP server config files: {summary.get('mcp_server_configs', 0)}",
        f"- MCP tool references: {summary.get('mcp_tool_references', 0)}",
        f"- Graphify nodes: {summary.get('graphify_nodes', 0)}",
        "",
        "## Agentic Structure Review",
        "",
        f"- Overall readiness grade: **{review['grade']}**",
        f"- Confirmed links: {summary.get('edge_classifications', {}).get('confirmed', 0)}",
        f"- Inferred links: {summary.get('edge_classifications', {}).get('inferred', 0)}",
        "",
        "## Confidence",
        "",
    ]
    for name, count in summary["confidence"].items():
        lines.append(f"- {name}: {count}")

    for heading, key in (
        ("Strengths", "strengths"),
        ("Weaknesses", "weaknesses"),
        ("Missing Owners", "missing_owners"),
        ("Stale Or Broken References", "stale_or_broken_references"),
        ("Duplicated Or Confusing Instruction Surfaces", "duplicated_instruction_surfaces"),
        ("Agent/Skill Coverage Summary", "agent_skill_coverage"),
        ("MCP/Tool Coverage Summary", "mcp_tool_coverage"),
        ("Suggested Improvements", "suggested_improvements"),
    ):
        lines.extend(["", f"## {heading}", ""])
        values = review[key]
        if values:
            lines.extend(f"- {value}" for value in values)
        else:
            lines.append("- none")

    lines.extend(["", "## Source Surfaces", "", "| Confidence | Kind | Path | Why Included |", "|---|---|---|---|"])
    for source in graph["sources"]:
        lines.append(f"| {source['confidence']} | `{source['kind']}` | `{source['path']}` | {source.get('inclusion_reason', '')} |")
    lines.extend(["", "## Facts Vs Guesses", ""])
    lines.append("- Confirmed facts come from matched files, existing paths, MCP config definitions, and Graphify output artifacts.")
    lines.append("- Inferred links come from text mentions, slug matches, and tool-name mentions that need human review before ownership is assumed.")
    lines.extend(
        [
            "",
            "## How To Use",
            "",
            "Use high-confidence nodes as real agent or skill surfaces.",
            "Use medium-confidence nodes as supporting automation/config.",
            "Use low-confidence nodes as clues that need human or agent review.",
            "Confirm source behavior in code before treating inferred ownership edges as fact.",
            "",
        ]
    )
    (out / "AGENT_GPS_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def build_quality_review(graph: dict) -> dict[str, list[str] | str]:
    summary = graph["summary"]
    nodes = graph["nodes"]
    edges = graph["edges"]
    strengths: list[str] = []
    weaknesses: list[str] = []
    missing_owners: list[str] = []
    stale_or_broken: list[str] = []
    duplicated: list[str] = []
    improvements: list[str] = []
    action_plan: list[dict[str, str]] = []

    agent_surface_count = summary.get("agent_surfaces", summary.get("canonical_agents", 0))
    skill_surface_count = summary.get("skill_surfaces", summary.get("canonical_skills", 0))

    if agent_surface_count:
        strengths.append(f"Found {agent_surface_count} explicit agent surface(s).")
    else:
        weaknesses.append("No explicit agent surfaces were found.")
        improvements.append("Add explicit agent definitions for recurring development domains.")
        action_plan.append(
            {
                "priority": "P1",
                "title": "Add explicit agent owners",
                "why": "Agents do less repeated discovery when ownership is declared in dedicated agent files.",
                "evidence": "No canonical agent surfaces were found.",
            }
        )

    if skill_surface_count:
        strengths.append(f"Found {skill_surface_count} reusable skill surface(s).")
    else:
        weaknesses.append("No reusable skill surfaces were found.")
        improvements.append("Add reusable skills for agent workflows that currently live only in prose.")
        action_plan.append(
            {
                "priority": "P1",
                "title": "Extract repeated instructions into skills",
                "why": "Shared skills keep agents from re-reading and re-inventing the same workflow guidance.",
                "evidence": "No canonical skill surfaces were found.",
            }
        )

    mcp_tool_count = summary.get("mcp_tools", 0)
    mcp_server_config_count = summary.get("mcp_server_configs", 0)
    mcp_tool_reference_count = summary.get("mcp_tool_references", 0)
    if mcp_tool_count and mcp_server_config_count:
        strengths.append(f"Mapped {mcp_tool_count} MCP/tool server(s) from repo-local config.")
        action_plan.append(
            {
                "priority": "P2",
                "title": "Make MCP/tool usage explicit",
                "why": "Agents can ask for the right tool faster when tool mentions are documented near the workflow that needs them.",
                "evidence": f"{summary.get('mcp_tools', 0)} MCP/tool node(s), {summary.get('edge_relations', {}).get('mentions_tool', 0)} tool mention edge(s).",
            }
        )
    elif mcp_tool_count:
        strengths.append(f"Found {mcp_tool_count} MCP server/tool reference(s) in agent permissions or tool lists.")
        weaknesses.append("MCP tools are referenced, but no repo-local MCP server config was detected.")
        improvements.append("Document where MCP servers are configured, or add a repo-local MCP inventory if the config is global.")
        action_plan.append(
            {
                "priority": "P2",
                "title": "Document MCP server source",
                "why": "Agents can see which MCP tools are allowed, but still need to know where those servers come from.",
                "evidence": f"{mcp_tool_reference_count} MCP tool reference(s), {mcp_server_config_count} repo-local MCP server config file(s).",
            }
        )
    else:
        weaknesses.append("No MCP/tool config or MCP tool references were detected.")
        improvements.append("Document MCP/tool availability in `.mcp.json` or an instruction file.")
        action_plan.append(
            {
                "priority": "P1",
                "title": "Document MCP/tool availability",
                "why": "Without a tool map, agents waste context guessing which integrations are available.",
                "evidence": "No MCP/tool config or MCP tool references were detected.",
            }
        )

    if summary.get("graphify_nodes", 0):
        strengths.append(f"Detected {summary['graphify_nodes']} Graphify node(s) for bridge mapping.")
    else:
        improvements.append("Run Graphify first when you want Agent GPS to bridge agents and skills to code/doc ownership.")
        action_plan.append(
            {
                "priority": "P3",
                "title": "Run Graphify before ownership review",
                "why": "The bridge is what turns agent instructions into concrete code/doc ownership evidence.",
                "evidence": "No Graphify nodes were detected.",
            }
        )

    referenced = [node for node in nodes if node.get("kind") in {"graphify_code", "graphify_doc"}]
    owned_paths = {node.get("path") for node in referenced}
    bridge_targets = {edge["target"] for edge in edges if edge["relation"] == "bridges_to_graphify"}
    for node in referenced:
        node_path = node.get("path")
        if node.get("kind", "").startswith("graphify_") and node["id"] not in bridge_targets:
            missing_owners.append(f"`{node_path}` appears in Graphify output but is not mentioned by an agent, skill, or instruction surface.")
    if not missing_owners and owned_paths:
        strengths.append("Every detected Graphify code/doc path has at least one agentic mention or bridge.")
    elif missing_owners:
        action_plan.append(
            {
                "priority": "P1",
                "title": "Assign owners to unbridged Graphify paths",
                "why": "Unowned code/doc areas force every agent to rediscover who should touch them.",
                "evidence": f"{len(missing_owners)} Graphify path(s) lack an agentic bridge.",
            }
        )

    inferred = summary.get("edge_classifications", {}).get("inferred", 0)
    confirmed = summary.get("edge_classifications", {}).get("confirmed", 0)
    if inferred > confirmed:
        weaknesses.append("More inferred links than confirmed links; ownership may be ambiguous.")
        improvements.append("Replace inferred mentions with explicit paths, owners, or generated-from links where possible.")
        action_plan.append(
            {
                "priority": "P2",
                "title": "Promote inferred links into confirmed links",
                "why": "Confirmed links let agents trust the map instead of spending context validating guesses.",
                "evidence": f"{inferred} inferred link(s) vs {confirmed} confirmed link(s).",
            }
        )

    source_paths = [source["path"] for source in graph["sources"]]
    for source in graph["sources"]:
        text_path = source["path"]
        if text_path.startswith("docs/") and source["confidence"] == LOW_CONFIDENCE:
            stale_or_broken.append(f"`{text_path}` is low-confidence related documentation; review for freshness and ownership.")

    instruction_names = Counter(Path(path).name for path in source_paths if Path(path).name in {"AGENTS.md", "CLAUDE.md"})
    for name, count in instruction_names.items():
        if count > 1:
            duplicated.append(f"Found {count} `{name}` files; make precedence and scope boundaries explicit.")
    if not duplicated:
        strengths.append("Instruction surfaces do not appear duplicated by filename.")
    else:
        action_plan.append(
            {
                "priority": "P1",
                "title": "Clarify instruction precedence",
                "why": "Multiple instruction files are useful only when agents can tell which one wins for a path.",
                "evidence": "; ".join(duplicated[:3]),
            }
        )

    grade_points = 0
    grade_points += 2 if agent_surface_count else 0
    grade_points += 2 if skill_surface_count else 0
    grade_points += 1 if mcp_tool_count else 0
    grade_points += 1 if summary.get("graphify_nodes", 0) else 0
    grade_points += 1 if not missing_owners else 0
    grade_points += 1 if confirmed >= inferred else 0
    grade = "A" if grade_points >= 7 else "B" if grade_points >= 5 else "C" if grade_points >= 3 else "D"

    return {
        "grade": grade,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "missing_owners": missing_owners,
        "stale_or_broken_references": stale_or_broken,
        "duplicated_instruction_surfaces": duplicated,
        "agent_skill_coverage": [
            f"Agent surfaces: {agent_surface_count}",
            f"Skill surfaces: {skill_surface_count}",
            f"Canonical agents: {summary.get('canonical_agents', 0)}",
            f"Canonical skills: {summary.get('canonical_skills', 0)}",
            f"Instruction docs: {summary.get('node_kinds', {}).get('instruction_doc', 0)}",
        ],
        "mcp_tool_coverage": [
            f"MCP/tool nodes: {summary.get('mcp_tools', 0)}",
            f"MCP server config files: {summary.get('mcp_server_configs', 0)}",
            f"MCP tool references: {summary.get('mcp_tool_references', 0)}",
            f"Tool allow edges: {summary.get('edge_relations', {}).get('allows_tool', 0)}",
            f"Tool definition edges: {summary.get('edge_relations', {}).get('defines_tool', 0)}",
            f"Tool mention edges: {summary.get('edge_relations', {}).get('mentions_tool', 0)}",
        ],
        "suggested_improvements": improvements,
        "action_plan": action_plan[:6],
    }


def build_recommendations(graph: dict) -> dict[str, list[dict[str, str]] | list[str]]:
    nodes = graph["nodes"]
    edges = graph["edges"]
    summary = graph["summary"]
    by_id = {node["id"]: node for node in nodes}
    proposed_agents: list[dict[str, str]] = []
    proposed_skills: list[dict[str, str]] = []
    instruction_cleanup: list[str] = []
    routing_rows: list[dict[str, str]] = []
    next_artifacts: list[str] = []

    agent_nodes = [node for node in nodes if node.get("kind") in {"claude_agent", "codex_agent", "devin_agent"}]
    skill_nodes = [node for node in nodes if node.get("kind") in {"canonical_skill", "claude_skill"}]
    instruction_nodes = [node for node in nodes if node.get("kind") in {"instruction_doc", "copilot_instruction", "cursor_rule", "windsurf_rule"}]

    for node in agent_nodes[:8]:
        proposed_agents.append(
            {
                "name": slug_from_recommendation_node(node, "agent"),
                "source": str(node.get("path") or node.get("label") or node["id"]),
                "purpose": str(node.get("excerpt") or node.get("description") or "Owns a recurring repository work area."),
            }
        )
    if not proposed_agents:
        for node in instruction_nodes[:6]:
            proposed_agents.append(
                {
                    "name": slug_from_recommendation_node(node, "agent"),
                    "source": str(node.get("path") or node.get("label") or node["id"]),
                    "purpose": f"Own the workflow described by {node.get('path') or node.get('label')}.",
                }
            )

    for node in skill_nodes[:10]:
        proposed_skills.append(
            {
                "name": slug_from_recommendation_node(node, "skill"),
                "source": str(node.get("path") or node.get("label") or node["id"]),
                "purpose": str(node.get("excerpt") or node.get("description") or "Reusable workflow guidance for agents."),
            }
        )
    if not proposed_skills:
        for node in instruction_nodes[:6]:
            proposed_skills.append(
                {
                    "name": slug_from_recommendation_node(node, "skill"),
                    "source": str(node.get("path") or node.get("label") or node["id"]),
                    "purpose": f"Extract repeatable guidance from {node.get('path') or node.get('label')}.",
                }
            )

    instruction_names = Counter(Path(str(node.get("path", ""))).name for node in instruction_nodes)
    for name, count in sorted(instruction_names.items()):
        if name and count > 1:
            instruction_cleanup.append(f"Declare precedence for the {count} `{name}` files and state which paths each one governs.")
    if not instruction_cleanup and instruction_nodes:
        instruction_cleanup.append("Keep the root instruction file as the entry point and link out to narrower path-scoped instructions.")
    if summary.get("mcp_tools", 0) and summary.get("mcp_server_configs", 0) == 0:
        instruction_cleanup.append("Add an MCP inventory that explains where referenced MCP servers are configured and which workflows may use them.")
    elif summary.get("mcp_tools", 0) == 0:
        instruction_cleanup.append("Add an MCP/tool availability section so agents know which integrations are allowed before they start work.")

    owner_candidates = [node for node in agent_nodes + skill_nodes + instruction_nodes if node.get("path")]
    route_edges = [edge for edge in edges if edge["relation"] in {"mentions_path", "bridges_to_graphify"}]
    for edge in route_edges:
        source = by_id.get(edge["source"], {})
        target = by_id.get(edge["target"], {})
        target_path = str(target.get("path") or "")
        source_path = str(source.get("path") or source.get("label") or "")
        if not target_path or not source_path:
            continue
        routing_rows.append(
            {
                "path": target_path,
                "owner": source_path,
                "reason": edge["relation"].replace("_", " "),
            }
        )
    if not routing_rows:
        for node in owner_candidates[:8]:
            for read_next in node.get("read_next", [])[:2]:
                routing_rows.append(
                    {
                        "path": str(read_next),
                        "owner": str(node.get("path") or node.get("label")),
                        "reason": "read next recommendation",
                    }
                )

    next_artifacts.extend(
        [
            "Create or update `.agents/AGENTS.md` with a path-to-owner routing table.",
            "Create canonical `.agents/skills/*/SKILL.md` files for repeated workflows.",
            "Add an instruction precedence section to the root agent instructions.",
        ]
    )
    if summary.get("graphify_nodes", 0) == 0:
        next_artifacts.append("Run Graphify and rebuild Agent GPS to connect these recommendations to code/doc nodes.")

    return {
        "proposed_agents": proposed_agents[:8],
        "proposed_skills": proposed_skills[:10],
        "instruction_cleanup": instruction_cleanup,
        "routing_rows": dedupe_dicts(routing_rows, ("path", "owner"))[:20],
        "next_artifacts": next_artifacts,
    }


def slug_from_recommendation_node(node: dict, suffix: str) -> str:
    path = str(node.get("path") or node.get("label") or node["id"])
    parts = [part for part in Path(path).parts if part not in {".", ".."}]
    if parts and parts[-1] in {"AGENT.md", "SKILL.md", "CLAUDE.md", "AGENTS.md"} and len(parts) > 1:
        value = parts[-2]
    else:
        value = Path(path).stem or str(node.get("label") or suffix)
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    if not slug:
        slug = suffix
    return slug


def dedupe_dicts(items: list[dict[str, str]], keys: tuple[str, ...]) -> list[dict[str, str]]:
    seen: set[tuple[str, ...]] = set()
    result: list[dict[str, str]] = []
    for item in items:
        marker = tuple(item.get(key, "") for key in keys)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def html_data(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def write_html(out: Path, graph: dict) -> None:
    data = html_data(graph)
    summary = graph["summary"]
    title = "Agent GPS"
    subtitle = f"{summary['sources']} sources, {summary['nodes']} nodes, {summary['edges']} edges"
    html_text = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__TITLE__</title>
  <style>
    :root { color-scheme: light; --bg:#f5f7fb; --panel:#ffffff; --panel-2:#eef3f8; --line:#c9d4df; --text:#17212b; --muted:#5d6f7e; --high:#087ea4; --medium:#a16207; --low:#be3455; --edge:#8fa1b2; --good:#2f855a; --button:#ffffff; --header:#ffffff; --tab:#eef3f8; --tab-active:#dbeafe; --graph:#f8fafc; --soft:#f1f5f9; }
    * { box-sizing: border-box; }
    body { margin:0; min-height:100vh; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; letter-spacing:0; }
    button, input, label, p { font-size:14px; }
    button, input { font:inherit; }
    button { border:1px solid var(--line); background:var(--button); color:var(--text); border-radius:6px; padding:8px 10px; cursor:pointer; }
    button:hover, button:focus-visible { border-color:var(--high); outline:none; }
    .app { min-height:100vh; display:grid; grid-template-rows:auto 1fr; }
    .shell-header { position:sticky; top:0; z-index:10; display:grid; grid-template-columns:minmax(220px, 1fr) auto auto; gap:18px; align-items:center; padding:14px 18px; border-bottom:1px solid var(--line); background:var(--header); box-shadow:0 1px 3px rgba(23,33,43,.08); }
    .brand h1 { margin:0; font-size:23px; line-height:1.1; }
    .brand p { margin:5px 0 0; color:var(--muted); }
    .metrics { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
    .metric { display:grid; gap:2px; min-width:72px; padding:7px 9px; border:1px solid var(--line); border-radius:6px; background:var(--soft); }
    .metric span { color:var(--muted); font-size:11px; text-transform:uppercase; }
    .metric strong { font-size:15px; }
    .tabs { display:flex; gap:6px; padding:4px; border:1px solid var(--line); border-radius:8px; background:var(--tab); }
    .tab { border:0; background:transparent; color:var(--muted); padding:8px 11px; }
    .tab[aria-selected="true"] { background:var(--tab-active); color:#0f3a63; }
    .view { display:none; min-height:0; }
    .view.active { display:block; }
    .map-view.active { display:grid; grid-template-rows:auto 1fr; min-height:0; }
    .topbar { display:flex; align-items:center; gap:14px; min-height:62px; padding:10px 18px; background:var(--panel-2); border-bottom:1px solid var(--line); overflow:hidden; }
    .filters { display:flex; align-items:center; gap:14px; min-width:0; flex:1 1 auto; }
    input[type="search"] { width:clamp(150px, 17vw, 260px); padding:9px 10px; border:1px solid var(--line); background:#ffffff; color:var(--text); border-radius:6px; }
    label { display:flex; align-items:center; gap:6px; margin:0; white-space:nowrap; color:var(--muted); }
    .confidence-row { display:flex; align-items:center; gap:10px; min-width:0; flex-wrap:wrap; }
    .confidence-row strong { color:var(--text); }
    .editor-control { display:flex; align-items:center; gap:8px; color:var(--muted); white-space:nowrap; }
    select { border:1px solid var(--line); background:#ffffff; color:var(--text); border-radius:6px; padding:8px 9px; }
    .toolbar { display:flex; gap:8px; flex:0 0 auto; margin-left:auto; }
    .map-workbench { position:relative; min-height:0; }
    .graph-stage { min-width:0; min-height:0; background:var(--graph); }
    svg { width:100%; height:calc(100vh - 134px); min-height:480px; display:block; }
    line { stroke:var(--edge); stroke-opacity:.34; }
    circle { stroke:#ffffff; stroke-width:1.5; cursor:pointer; }
    text { fill:var(--text); font-size:11px; pointer-events:none; }
    .inspector { display:none; position:absolute; top:18px; right:18px; width:min(360px, calc(100% - 36px)); max-height:calc(100vh - 184px); border:1px solid var(--line); border-radius:8px; background:var(--panel); padding:16px; overflow:auto; box-shadow:0 18px 48px rgba(23,33,43,.18); }
    .inspector.open { display:block; }
    .inspector-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }
    .icon-button { width:30px; height:30px; display:grid; place-items:center; padding:0; }
    .inspector-actions { display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 12px; }
    .tool-button { display:inline-flex; align-items:center; justify-content:center; min-height:32px; padding:7px 9px; border:1px solid var(--line); border-radius:6px; background:var(--button); color:var(--text); text-decoration:none; font-size:13px; cursor:pointer; }
    .tool-button:hover, .tool-button:focus-visible, .path-link:hover, .path-link:focus-visible { border-color:var(--high); color:var(--high); outline:none; }
    .copy-status { min-height:18px; margin:0 0 8px; color:var(--muted); font-size:12px; }
    .path-link { display:inline; color:#0f5f8c; text-decoration:none; border-bottom:1px solid rgba(8,126,164,.35); }
    .inspector h2, .page-eyebrow { margin:0 0 8px; color:var(--muted); font-size:12px; text-transform:uppercase; }
    .inspector h1 { margin:0 0 8px; font-size:20px; line-height:1.2; }
    .page { max-width:1180px; margin:0 auto; padding:24px 22px 42px; }
    .page-header { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:18px; align-items:end; margin-bottom:22px; }
    .page-header h1 { margin:0; font-size:30px; line-height:1.1; }
    .page-header p { margin:8px 0 0; color:var(--muted); max-width:760px; line-height:1.5; }
    .grade-badge { display:grid; place-items:center; min-width:86px; min-height:86px; border:1px solid var(--line); border-radius:8px; background:var(--panel); }
    .grade-badge span { color:var(--muted); font-size:11px; text-transform:uppercase; }
    .grade-badge strong { font-size:38px; color:var(--medium); line-height:1; }
    .grid { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:16px; }
    .grid.three { grid-template-columns:repeat(3, minmax(0,1fr)); }
    .panel { border:1px solid var(--line); border-radius:8px; background:var(--panel); padding:16px; }
    .panel h2 { margin:0 0 10px; font-size:16px; }
    .panel p { margin:8px 0 0; color:var(--muted); line-height:1.45; }
    .panel ul { margin:0; padding-left:18px; }
    .panel li { margin:7px 0; color:var(--text); line-height:1.35; }
    .action-list, .recommendation-list, .report-list { display:grid; gap:10px; }
    .action, .recommendation, .report-card { padding:12px; border:1px solid var(--line); border-radius:7px; background:#fbfdff; }
    .action-title { display:flex; gap:8px; align-items:center; font-weight:700; }
    .priority { min-width:30px; padding:2px 6px; border:1px solid var(--line); border-radius:4px; color:var(--high); font-size:11px; text-align:center; }
    .recommendation strong, .report-card strong { display:block; margin-bottom:4px; }
    .file-chip { display:inline-block; margin-top:8px; padding:4px 7px; border:1px solid var(--line); border-radius:6px; background:var(--soft); color:var(--text); font-family:ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size:12px; }
    .table-wrap { overflow:auto; border:1px solid var(--line); border-radius:8px; }
    table { width:100%; border-collapse:collapse; min-width:640px; }
    th, td { padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
    th { color:var(--muted); font-size:12px; text-transform:uppercase; background:var(--panel-2); }
    tr:last-child td { border-bottom:0; }
    .muted { color:var(--muted); }
    .stat { display:flex; justify-content:space-between; gap:12px; border-bottom:1px solid var(--line); padding:7px 0; }
    .stat:last-child { border-bottom:0; }
    .pill { display:inline-block; margin:3px 4px 3px 0; padding:3px 7px; border:1px solid var(--line); border-radius:999px; color:var(--muted); font-size:12px; }
    .detail-block { margin:14px 0; }
    .detail-block h3 { margin:0 0 6px; font-size:12px; color:var(--muted); text-transform:uppercase; }
    .detail-block ul { margin:0; padding-left:18px; }
    .detail-block li { margin:5px 0; font-size:13px; }
    .excerpt { padding:10px; background:var(--soft); border:1px solid var(--line); border-radius:6px; color:var(--text); }
    .path { word-break:break-word; color:var(--muted); }
    @media (max-width: 1100px) { .shell-header { grid-template-columns:1fr; } .metrics, .tabs { justify-content:flex-start; } .inspector { left:18px; right:18px; width:auto; max-height:44vh; } svg { height:62vh; } .grid, .grid.three { grid-template-columns:1fr; } }
    @media (max-width: 700px) { .shell-header { padding:12px; } .topbar, .filters { align-items:stretch; flex-direction:column; } .toolbar { margin-left:0; } input[type="search"] { width:100%; } .page { padding:18px 14px 32px; } .page-header { grid-template-columns:1fr; } .tabs { overflow:auto; } }
  </style>
</head>
<body>
  <div class="app">
    <header class="shell-header">
      <div class="brand">
        <h1>__TITLE__</h1>
        <p>__SUBTITLE__</p>
      </div>
      <div class="metrics" aria-label="Graph summary">
        <div class="metric"><span>Sources</span><strong>__SOURCES__</strong></div>
        <div class="metric"><span>Nodes</span><strong>__NODES__</strong></div>
        <div class="metric"><span>Edges</span><strong>__EDGES__</strong></div>
      </div>
      <nav class="tabs" aria-label="Agent GPS sections">
        <button class="tab" type="button" data-tab="map" aria-selected="true">Map</button>
        <button class="tab" type="button" data-tab="review" aria-selected="false">Review</button>
        <button class="tab" type="button" data-tab="recommendations" aria-selected="false">Recommendations</button>
        <button class="tab" type="button" data-tab="reports" aria-selected="false">Reports</button>
      </nav>
    </header>
    <main>
      <section id="mapView" class="view map-view active" data-view="map">
        <div class="topbar" aria-label="Graph filters">
          <div class="filters">
            <input id="search" type="search" placeholder="Find node">
            <div class="confidence-row" aria-label="Show nodes by certainty">
              <strong>Show nodes by certainty</strong>
              <label title="Matched a real agent, skill, instruction, MCP/tool, or Graphify artifact."><input class="confidence" type="checkbox" value="high" checked> Verified</label>
              <label title="Found supporting config, scripts, or existing repository paths."><input class="confidence" type="checkbox" value="medium" checked> Supporting context</label>
              <label title="Related or inferred; verify before trusting it."><input class="confidence" type="checkbox" value="low" checked> Review first</label>
            </div>
          </div>
          <label class="editor-control" title="Controls how source paths open from node details.">
            Open paths in
            <select id="editorMode">
              <option value="copy">Copy path</option>
              <option value="vscode">VS Code</option>
              <option value="cursor">Cursor</option>
              <option value="windsurf">Windsurf</option>
              <option value="browser">Browser file tab</option>
            </select>
          </label>
          <div class="toolbar">
            <button id="fit" type="button">Fit</button>
            <button id="zoomOut" type="button">-</button>
            <button id="zoomIn" type="button">+</button>
          </div>
        </div>
        <div class="map-workbench">
          <div class="graph-stage">
            <svg id="graph" role="img" aria-label="Agent GPS graph"></svg>
          </div>
          <section id="inspector" class="inspector" aria-labelledby="selectionTitle">
            <div class="inspector-head">
              <h2 id="selectionTitle">Selection</h2>
              <button id="closeInspector" class="icon-button" type="button" aria-label="Close selection">x</button>
            </div>
            <div id="detail" class="muted">Select a node.</div>
          </section>
        </div>
      </section>
      <section class="view" data-view="review">
        <div class="page">
          <div class="page-header">
            <div>
              <div class="page-eyebrow">Working Environment Review</div>
              <h1>What this map means for agents</h1>
              <p>Agent GPS separates proven navigation surfaces from places where agents still need to infer, re-read, or ask for help. The goal is less discovery work and better handoffs.</p>
            </div>
            <div class="grade-badge"><span>Grade</span><strong id="reviewGrade">-</strong></div>
          </div>
          <div class="grid three" id="reviewStats"></div>
          <div class="grid" style="margin-top:16px">
            <section class="panel"><h2>Strengths</h2><div id="reviewStrengths"></div></section>
            <section class="panel"><h2>Gaps</h2><div id="reviewGaps"></div></section>
          </div>
          <section class="panel" style="margin-top:16px">
            <h2>Fix first</h2>
            <div id="reviewActions" class="action-list"></div>
          </section>
        </div>
      </section>
      <section class="view" data-view="recommendations">
        <div class="page">
          <div class="page-header">
            <div>
              <div class="page-eyebrow">Recommended Structure</div>
              <h1>Proposed agents, skills, and routing</h1>
              <p>These are the next artifacts Agent GPS would create or update so future agents can start closer to the right context.</p>
            </div>
          </div>
          <div class="grid">
            <section class="panel"><h2>Proposed agents</h2><div id="proposedAgents" class="recommendation-list"></div></section>
            <section class="panel"><h2>Proposed skills</h2><div id="proposedSkills" class="recommendation-list"></div></section>
          </div>
          <section class="panel" style="margin-top:16px">
            <h2>Routing table</h2>
            <div id="routingTable"></div>
          </section>
          <section class="panel" style="margin-top:16px">
            <h2>Next artifacts</h2>
            <div id="nextArtifacts"></div>
          </section>
        </div>
      </section>
      <section class="view" data-view="reports">
        <div class="page">
          <div class="page-header">
            <div>
              <div class="page-eyebrow">Generated Files</div>
              <h1>Reports and machine-readable outputs</h1>
              <p>This view summarizes the generated reports without leaving Agent GPS. The files are still written beside this HTML for review, versioning, and automation.</p>
            </div>
          </div>
          <div class="grid">
            <section class="panel">
              <h2>In-app reports</h2>
              <div class="report-list">
                <div class="report-card"><strong>Agent GPS Report</strong><span class="muted">Readiness grade, strengths, gaps, evidence, and usage notes are shown in the Review tab.</span><span class="file-chip">AGENT_GPS_REPORT.md</span></div>
                <div class="report-card"><strong>Recommendations</strong><span class="muted">Proposed agents, skills, routing rows, and next artifacts are shown in the Recommendations tab.</span><span class="file-chip">AGENT_GPS_RECOMMENDATIONS.md</span></div>
                <div class="report-card"><strong>Graphify Bridge</strong><span class="muted">Bridge status is included in the review findings and written as a standalone artifact.</span><span class="file-chip">AGENT_GPS_BRIDGE.md</span></div>
              </div>
            </section>
            <section class="panel">
              <h2>Generated artifacts</h2>
              <div id="artifactTable"></div>
            </section>
          </div>
        </div>
      </section>
    </main>
  </div>
  <script>
    const graph = __DATA__;
    const svg = document.getElementById('graph');
    const search = document.getElementById('search');
    const editorMode = document.getElementById('editorMode');
    const inspector = document.getElementById('inspector');
    const detail = document.getElementById('detail');
    const colors = { high:'#087ea4', medium:'#d97706', low:'#be3455', undefined:'#64748b' };
    const evidenceLabels = {
      high: 'Verified',
      medium: 'Supporting context',
      low: 'Review first',
      undefined: 'Unclassified'
    };
    const evidenceExplanations = {
      high: 'Matched a real agent, skill, instruction, MCP/tool, or Graphify artifact.',
      medium: 'Found supporting config, scripts, or existing repository paths.',
      low: 'Related or inferred; verify before trusting it.'
    };
    let scale = 1, ox = 0, oy = 0, selected = null;
    const minScale = 0.05;
    const nodes = graph.nodes.map((n, i) => ({...n, x: Math.cos(i * 2.399) * (90 + i * 1.7), y: Math.sin(i * 2.399) * (90 + i * 1.7)}));
    const byId = new Map(nodes.map(n => [n.id, n]));
    const edges = graph.edges.map(e => ({...e, s: byId.get(e.source), t: byId.get(e.target)})).filter(e => e.s && e.t);
    const esc = (value) => String(value || '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    const list = (items) => items && items.length ? `<ul>${items.map(item => `<li>${esc(item)}</li>`).join('')}</ul>` : '<p class="muted">none</p>';
    const openablePath = (path) => Boolean(path && path !== '.' && !String(path).startsWith('http') && !String(path).includes(':'));
    function normalizePathSlashes(value) {
      return String(value || '').split(String.fromCharCode(92)).join('/');
    }
    function absolutePath(path) {
      const root = normalizePathSlashes(graph.root).replace(new RegExp('/+$'), '');
      const value = normalizePathSlashes(path).replace(new RegExp('^/+'), '');
      if (!root || !value || value === '.') return value;
      return `${root}/${value}`;
    }
    const pathLink = (path, text = path) => openablePath(path) ? `<a class="path-link" href="#" data-path="${esc(path)}">${esc(text)}</a>` : esc(text);
    const pathList = (items) => items && items.length ? `<ul>${items.map(item => `<li>${pathLink(item)}</li>`).join('')}</ul>` : '<p class="muted">none</p>';
    function editorUrl(path, mode = editorMode.value) {
      const absolute = absolutePath(path);
      const forward = normalizePathSlashes(absolute);
      if (mode === 'vscode') return `vscode://file/${encodeURI(forward)}`;
      if (mode === 'cursor') return `cursor://file/${encodeURI(forward)}`;
      if (mode === 'windsurf') return `windsurf://file/${encodeURI(forward)}`;
      if (mode === 'browser') return `file:///${encodeURI(forward)}`;
      return '';
    }
    function openCommand(path) {
      const absolute = absolutePath(path);
      const quoted = `"${absolute}"`;
      const mode = editorMode.value;
      if (mode === 'vscode') return `code -g ${quoted}`;
      if (mode === 'cursor') return `cursor ${quoted}`;
      if (mode === 'windsurf') return `windsurf ${quoted}`;
      if (mode === 'browser') return editorUrl(path, 'browser');
      return absolute;
    }
    function nodeBrief(n) {
      return [
        `Agent GPS node: ${n.label || n.id}`,
        `What: ${n.what || n.kind || ''}`,
        n.path ? `Path: ${n.path}` : '',
        n.inclusion_reason ? `Why included: ${n.inclusion_reason}` : '',
        n.excerpt ? `Excerpt: ${n.excerpt}` : '',
        n.read_next && n.read_next.length ? `Read next: ${n.read_next.join(', ')}` : ''
      ].filter(Boolean).join(String.fromCharCode(10));
    }
    async function copyText(value, statusEl) {
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(value);
        } else {
          const temp = document.createElement('textarea');
          temp.value = value;
          temp.setAttribute('readonly', '');
          temp.style.position = 'fixed';
          temp.style.left = '-9999px';
          document.body.appendChild(temp);
          temp.select();
          document.execCommand('copy');
          temp.remove();
        }
        if (statusEl) statusEl.textContent = 'Copied.';
      } catch (error) {
        if (statusEl) statusEl.textContent = 'Copy failed. Select the text manually.';
      }
    }
    function openPath(path, statusEl) {
      if (!openablePath(path)) return;
      const mode = editorMode.value;
      if (mode === 'copy') {
        copyText(absolutePath(path), statusEl);
        return;
      }
      window.open(editorUrl(path, mode), '_blank', 'noopener');
      if (statusEl) statusEl.textContent = `Opened with ${editorMode.options[editorMode.selectedIndex].text}.`;
    }
    function setTab(tabName) {
      document.querySelectorAll('.tab').forEach(tab => tab.setAttribute('aria-selected', String(tab.dataset.tab === tabName)));
      document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.dataset.view === tabName));
      if (tabName === 'map') requestAnimationFrame(fit);
      if (location.hash.slice(1) !== tabName) history.replaceState(null, '', `#${tabName}`);
    }
    function renderReview() {
      const review = graph.review || {};
      const actions = review.action_plan || [];
      const actionHtml = actions.length ? actions.map(item => `
        <div class="action">
          <div class="action-title"><span class="priority">${esc(item.priority)}</span><span>${esc(item.title)}</span></div>
          <p>${esc(item.why)}</p>
          <p><strong>Evidence:</strong> ${esc(item.evidence)}</p>
        </div>
      `).join('') : '<p class="muted">No immediate fixes detected.</p>';
      const stats = [
        ['Confirmed links', graph.summary.edge_classifications?.confirmed || 0],
        ['Inferred links', graph.summary.edge_classifications?.inferred || 0],
        ['MCP/tools', graph.summary.mcp_tools || 0],
      ].map(([label, value]) => `<section class="panel"><h2>${esc(label)}</h2><p><strong>${esc(value)}</strong></p></section>`).join('');
      document.getElementById('reviewGrade').textContent = review.grade || '-';
      document.getElementById('reviewStats').innerHTML = stats;
      document.getElementById('reviewStrengths').innerHTML = list(review.strengths);
      document.getElementById('reviewGaps').innerHTML = list(review.weaknesses);
      document.getElementById('reviewActions').innerHTML = actionHtml;
    }
    function renderRecommendations() {
      const recs = graph.recommendations || {};
      const cards = (items) => items && items.length ? items.map(item => `
        <div class="recommendation">
          <strong>${esc(item.name || item.path || 'recommended item')}</strong>
          <p>${esc(item.purpose || item.owner || '')}</p>
          <p><span class="path">${esc(item.source || item.path || '')}</span>${item.reason ? ` - ${esc(item.reason)}` : ''}</p>
        </div>
      `).join('') : '<p class="muted">No recommendations generated.</p>';
      document.getElementById('proposedAgents').innerHTML = cards(recs.proposed_agents);
      document.getElementById('proposedSkills').innerHTML = cards(recs.proposed_skills);
      document.getElementById('nextArtifacts').innerHTML = list(recs.next_artifacts);
      const rows = recs.routing_rows || [];
      document.getElementById('routingTable').innerHTML = rows.length ? `
        <div class="table-wrap"><table>
          <thead><tr><th>Path</th><th>Recommended owner/context</th><th>Evidence</th></tr></thead>
          <tbody>${rows.map(row => `<tr><td><span class="path">${esc(row.path)}</span></td><td>${esc(row.owner)}</td><td>${esc(row.reason)}</td></tr>`).join('')}</tbody>
        </table></div>
      ` : '<p class="muted">No routing rows were generated.</p>';
    }
    function renderArtifacts() {
      const artifacts = [
        ['agent-gps.html', 'This navigable report app.'],
        ['agent-gps.graph.json', 'Complete graph, review, and recommendation payload.'],
        ['AGENT_GPS_REPORT.md', 'Markdown review artifact for humans and version control.'],
        ['AGENT_GPS_RECOMMENDATIONS.md', 'Markdown implementation handoff for agent/skill/routing upgrades.'],
        ['AGENT_GPS_BRIDGE.md', 'Graphify bridge artifact.'],
        ['manifest.json', 'Source hashes for check and diff.']
      ];
      document.getElementById('artifactTable').innerHTML = `
        <div class="table-wrap"><table>
          <thead><tr><th>File</th><th>Purpose</th></tr></thead>
          <tbody>${artifacts.map(([file, purpose]) => `<tr><td><span class="file-chip">${esc(file)}</span></td><td>${esc(purpose)}</td></tr>`).join('')}</tbody>
        </table></div>
      `;
    }
    function visible(n) {
      const allowed = new Set([...document.querySelectorAll('.confidence:checked')].map(i => i.value));
      const q = search.value.trim().toLowerCase();
      if (n.confidence && !allowed.has(n.confidence)) return false;
      if (!q) return true;
      return [n.label,n.path,n.kind,n.description,n.what,n.inclusion_reason,n.excerpt].join(' ').toLowerCase().includes(q);
    }
    function tick() {
      for (let i = 0; i < 90; i++) {
        for (const e of edges) {
          const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y;
          const d = Math.max(1, Math.hypot(dx, dy));
          const f = (d - 130) * 0.002;
          e.s.x += dx * f; e.s.y += dy * f; e.t.x -= dx * f; e.t.y -= dy * f;
        }
        for (let a = 0; a < nodes.length; a++) for (let b = a + 1; b < nodes.length; b++) {
          const n = nodes[a], m = nodes[b], dx = m.x - n.x, dy = m.y - n.y;
          const d2 = Math.max(30, dx*dx + dy*dy), f = 45 / d2;
          n.x -= dx * f; n.y -= dy * f; m.x += dx * f; m.y += dy * f;
        }
      }
    }
    function fit() {
      const shown = nodes.filter(visible);
      const w = svg.clientWidth, h = svg.clientHeight;
      const xs = shown.map(n => n.x), ys = shown.map(n => n.y);
      if (!shown.length || !w || !h) return;
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
      scale = Math.max(minScale, Math.min(2.4, Math.min((w - 120) / Math.max(1, maxX - minX), (h - 120) / Math.max(1, maxY - minY))));
      ox = w / 2 - ((minX + maxX) / 2) * scale; oy = h / 2 - ((minY + maxY) / 2) * scale;
      render();
    }
    function sx(x) { return x * scale + ox; }
    function sy(y) { return y * scale + oy; }
    function render() {
      const shown = new Set(nodes.filter(visible).map(n => n.id));
      svg.innerHTML = '';
      for (const e of edges) {
        if (!shown.has(e.source) || !shown.has(e.target)) continue;
        const line = document.createElementNS('http://www.w3.org/2000/svg','line');
        line.setAttribute('x1', sx(e.s.x)); line.setAttribute('y1', sy(e.s.y)); line.setAttribute('x2', sx(e.t.x)); line.setAttribute('y2', sy(e.t.y));
        svg.appendChild(line);
      }
      for (const n of nodes) {
        if (!shown.has(n.id)) continue;
        const g = document.createElementNS('http://www.w3.org/2000/svg','g');
        const c = document.createElementNS('http://www.w3.org/2000/svg','circle');
        c.setAttribute('cx', sx(n.x)); c.setAttribute('cy', sy(n.y)); c.setAttribute('r', n.id === selected ? 8 : 5.5); c.setAttribute('fill', colors[n.confidence] || colors.undefined);
        c.addEventListener('click', () => select(n));
        const t = document.createElementNS('http://www.w3.org/2000/svg','text');
        t.setAttribute('x', sx(n.x) + 8); t.setAttribute('y', sy(n.y) + 4); t.textContent = n.label || n.path || n.id;
        g.appendChild(c); g.appendChild(t); svg.appendChild(g);
      }
    }
    function select(n) {
      selected = n.id;
      const relationGroups = Object.entries(n.connections_by_relation || {}).map(([relation, items]) => {
        const rows = items.map(item => `<li><span class="pill">${esc(item.classification)}</span>${esc(item.direction)}: ${esc(item.label)}${item.path ? ` <span class="path">(${pathLink(item.path)})</span>` : ''}</li>`).join('');
        return `<div class="detail-block"><h3>${esc(relation)}</h3><ul>${rows}</ul></div>`;
      }).join('');
      const actionHtml = [
        openablePath(n.path) ? `<button id="openSource" class="tool-button" type="button">Open source</button>` : '',
        n.path ? '<button id="copyPath" class="tool-button" type="button">Copy path</button>' : '',
        n.path ? '<button id="copyOpenCommand" class="tool-button" type="button">Copy open command</button>' : '',
        '<button id="copyBrief" class="tool-button" type="button">Copy brief</button>'
      ].filter(Boolean).join('');
      detail.innerHTML = `
        <h1>${esc(n.label || n.id)}</h1>
        <p class="path">${n.path ? pathLink(n.path) : ''}</p>
        <div class="inspector-actions">${actionHtml}</div>
        <p id="copyStatus" class="copy-status" aria-live="polite"></p>
        <div class="stat"><span>What</span><strong>${esc(n.what || n.kind)}</strong></div>
        <div class="stat"><span>Kind</span><strong>${esc(n.kind)}</strong></div>
        <div class="stat"><span>Certainty</span><strong>${esc(evidenceLabels[n.confidence] || n.confidence || '-')}</strong></div>
        <div class="detail-block"><h3>Why included</h3><p>${esc(n.inclusion_reason || '')}</p></div>
        <div class="detail-block"><h3>Why this certainty</h3><p>${esc(evidenceExplanations[n.confidence] || n.confidence_explanation || '')}</p></div>
        <div class="detail-block"><h3>Excerpt</h3><div class="excerpt">${esc(n.excerpt || n.description || '')}</div></div>
        <div class="detail-block"><h3>Confirmed facts</h3>${list(n.confirmed_facts)}</div>
        <div class="detail-block"><h3>Inferred links</h3>${list(n.inferred_links)}</div>
        <div class="detail-block"><h3>Read next</h3>${pathList(n.read_next)}</div>
        <div class="detail-block"><h3>Connections by relation</h3>${relationGroups || '<p class="muted">none</p>'}</div>
      `;
      const statusEl = document.getElementById('copyStatus');
      document.getElementById('openSource')?.addEventListener('click', () => openPath(n.path || '', statusEl));
      document.getElementById('copyPath')?.addEventListener('click', () => copyText(absolutePath(n.path || ''), statusEl));
      document.getElementById('copyOpenCommand')?.addEventListener('click', () => copyText(openCommand(n.path || ''), statusEl));
      document.getElementById('copyBrief')?.addEventListener('click', () => copyText(nodeBrief(n), statusEl));
      inspector.classList.add('open');
      render();
    }
    document.querySelectorAll('.tab').forEach(tab => tab.addEventListener('click', () => setTab(tab.dataset.tab)));
    editorMode.value = localStorage.getItem('agentGpsEditorMode') || 'copy';
    editorMode.addEventListener('change', () => localStorage.setItem('agentGpsEditorMode', editorMode.value));
    document.addEventListener('click', event => {
      const target = event.target.closest('a[data-path]');
      if (!target) return;
      event.preventDefault();
      openPath(target.dataset.path || '', document.getElementById('copyStatus'));
    });
    renderReview(); renderRecommendations(); renderArtifacts(); tick(); setTab(location.hash.slice(1) || 'map'); fit();
    document.getElementById('fit').onclick = fit;
    document.getElementById('closeInspector').onclick = () => { inspector.classList.remove('open'); selected = null; render(); };
    document.getElementById('zoomOut').onclick = () => { scale = Math.max(minScale, scale * 0.8); render(); };
    document.getElementById('zoomIn').onclick = () => { scale = Math.min(3.5, scale * 1.25); render(); };
    search.oninput = render;
    document.querySelectorAll('.confidence').forEach(i => i.onchange = render);
    svg.addEventListener('wheel', e => { e.preventDefault(); scale = Math.max(minScale, Math.min(3.5, scale * (e.deltaY < 0 ? 1.12 : 0.88))); render(); }, {passive:false});
  </script>
</body>
</html>
"""
    html_text = (
        html_text.replace("__TITLE__", html.escape(title))
        .replace("__SUBTITLE__", html.escape(subtitle))
        .replace("__SOURCES__", str(summary["sources"]))
        .replace("__NODES__", str(summary["nodes"]))
        .replace("__EDGES__", str(summary["edges"]))
        .replace("__DATA__", data)
    )
    (out / "agent-gps.html").write_text(html_text, encoding="utf-8")


def write_manifest(out: Path, graph: dict) -> None:
    manifest = {
        "schema": "agent-gps.manifest.v1",
        "generated_at": graph["generated_at"],
        "root": graph["root"],
        "source_hashes": {source["path"]: source["hash"] for source in graph["sources"]},
        "summary": graph["summary"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_bridge_report(out: Path, graph: dict) -> None:
    lines = [
        "# Agent GPS Graphify Bridge",
        "",
        f"Generated: {graph['generated_at']}",
        f"Root: `{graph['root']}`",
        "",
        "## Bridged Paths",
        "",
    ]
    bridge_edges = [edge for edge in graph["edges"] if edge["relation"] == "bridges_to_graphify"]
    by_id = {node["id"]: node for node in graph["nodes"]}
    if bridge_edges:
        lines.extend(["| Agentic Surface | Graphify Node | Classification |", "|---|---|---|"])
        for edge in bridge_edges:
            source = by_id.get(edge["source"], {})
            target = by_id.get(edge["target"], {})
            source_label = source.get("path") or source.get("label") or edge["source"]
            target_label = target.get("path") or target.get("label") or edge["target"]
            lines.append(f"| `{source_label}` | `{target_label}` | {edge.get('classification', 'confirmed')} |")
    else:
        lines.append("- No Graphify bridge edges were found.")
    lines.extend(["", "## Unbridged Graphify Nodes", ""])
    bridged_targets = {edge["target"] for edge in bridge_edges}
    unbridged = [node for node in graph["nodes"] if str(node.get("kind", "")).startswith("graphify_") and node["id"] not in bridged_targets]
    if unbridged:
        lines.extend(f"- `{node.get('path') or node.get('label')}`" for node in unbridged)
    else:
        lines.append("- none")
    (out / "AGENT_GPS_BRIDGE.md").write_text("\n".join(lines), encoding="utf-8")


def write_recommendations(out: Path, graph: dict) -> None:
    recommendations = build_recommendations(graph)
    lines = [
        "# Agent GPS Recommendations",
        "",
        f"Generated: {graph['generated_at']}",
        f"Root: `{graph['root']}`",
        "",
        "These recommendations translate the Agent GPS diagnosis into concrete changes that should reduce repeated discovery, clarify handoffs, and make agents more useful to each other.",
        "",
        "## Proposed Agents",
        "",
    ]
    proposed_agents = recommendations["proposed_agents"]
    if proposed_agents:
        lines.extend(["| Agent | Seed Source | Purpose |", "|---|---|---|"])
        for item in proposed_agents:
            lines.append(f"| `{item['name']}` | `{item['source']}` | {item['purpose']} |")
    else:
        lines.append("- No agent proposals were generated.")

    lines.extend(["", "## Proposed Skills", ""])
    proposed_skills = recommendations["proposed_skills"]
    if proposed_skills:
        lines.extend(["| Skill | Seed Source | Purpose |", "|---|---|---|"])
        for item in proposed_skills:
            lines.append(f"| `{item['name']}` | `{item['source']}` | {item['purpose']} |")
    else:
        lines.append("- No skill proposals were generated.")

    lines.extend(["", "## Instruction Cleanup", ""])
    cleanup_items = recommendations["instruction_cleanup"]
    if cleanup_items:
        lines.extend(f"- {item}" for item in cleanup_items)
    else:
        lines.append("- No instruction cleanup recommendations were generated.")

    lines.extend(["", "## Routing Table", ""])
    routing_rows = recommendations["routing_rows"]
    if routing_rows:
        lines.extend(["| Path | Recommended Owner/Context | Evidence |", "|---|---|---|"])
        for row in routing_rows:
            lines.append(f"| `{row['path']}` | `{row['owner']}` | {row['reason']} |")
    else:
        lines.append("- No routing rows were generated.")

    lines.extend(["", "## Next Artifacts", ""])
    lines.extend(f"- {item}" for item in recommendations["next_artifacts"])
    lines.append("")
    (out / "AGENT_GPS_RECOMMENDATIONS.md").write_text("\n".join(lines), encoding="utf-8")


def command_build(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    graph = build_graph(root)
    (out / "agent-gps.graph.json").write_text(json.dumps(graph, indent=2), encoding="utf-8")
    write_report(out, graph)
    write_bridge_report(out, graph)
    write_recommendations(out, graph)
    write_html(out, graph)
    write_manifest(out, graph)
    print(f"Agent GPS built: {graph['summary']['sources']} sources, {graph['summary']['nodes']} nodes, {graph['summary']['edges']} edges -> {out}")
    return 0


def command_report(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    graph = build_graph(root)
    write_report(out, graph)
    print(f"Agent GPS report written -> {out / 'AGENT_GPS_REPORT.md'}")
    return 0


def command_bridge_graphify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    graph = build_graph(root)
    write_bridge_report(out, graph)
    print(f"Agent GPS Graphify bridge written -> {out / 'AGENT_GPS_BRIDGE.md'}")
    return 0


def load_manifest(out: Path) -> dict:
    path = out / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing; run build first")
    return json.loads(path.read_text(encoding="utf-8"))


def current_hashes(root: Path) -> dict[str, str]:
    return {source["path"]: source["hash"] for source in detect_sources(root)}


def diff_hashes(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "changed": sorted(path for path in set(old) & set(new) if old[path] != new[path]),
    }


def command_check(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    manifest = load_manifest(out)
    changes = diff_hashes(manifest.get("source_hashes", {}), current_hashes(root))
    total = sum(len(value) for value in changes.values())
    if total:
        print("Agent GPS is stale.")
        for name, paths in changes.items():
            if paths:
                print(f"{name}:")
                for path in paths:
                    print(f"  - {path}")
        return 1
    print("Agent GPS check passed.")
    return 0


def command_diff(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    manifest = load_manifest(out)
    changes = diff_hashes(manifest.get("source_hashes", {}), current_hashes(root))
    lines = ["# Agent GPS Diff", "", f"Generated: {utc_now()}", ""]
    for name in ("added", "removed", "changed"):
        paths = changes[name]
        lines.extend([f"## {name.title()}", ""])
        if paths:
            lines.extend(f"- `{path}`" for path in paths)
        else:
            lines.append("- none")
        lines.append("")
    (out / "AGENT_GPS_DIFF.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Agent GPS diff written -> {out / 'AGENT_GPS_DIFF.md'}")
    return 0 if not sum(len(value) for value in changes.values()) else 1


def command_watch(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    out = Path(args.out).resolve()
    interval = max(2, int(args.interval))
    print(f"Watching {root} every {interval}s. Press Ctrl+C to stop.")
    previous: dict[str, str] | None = None
    try:
        while True:
            now = current_hashes(root)
            if now != previous:
                command_build(argparse.Namespace(root=str(root), out=str(out)))
                previous = now
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped.")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a portable Agent GPS map for AI agent, skill, and instruction surfaces.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "check", "diff", "watch", "report", "bridge-graphify"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".", help="Project root to scan.")
        p.add_argument("--out", default="agent-gps-out", help="Output directory.")
        if name == "watch":
            p.add_argument("--interval", default=10, help="Polling interval in seconds.")
    args = parser.parse_args(argv)
    if args.command == "build":
        return command_build(args)
    if args.command == "check":
        return command_check(args)
    if args.command == "diff":
        return command_diff(args)
    if args.command == "watch":
        return command_watch(args)
    if args.command == "report":
        return command_report(args)
    if args.command == "bridge-graphify":
        return command_bridge_graphify(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
