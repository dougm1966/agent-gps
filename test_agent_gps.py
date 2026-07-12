import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import agent_gps


class AgentGpsV2Tests(unittest.TestCase):
    def make_repo(self) -> tempfile.TemporaryDirectory:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / ".agents" / "skills" / "reviewer").mkdir(parents=True)
        (root / ".claude" / "agents" / "builder").mkdir(parents=True)
        (root / ".claude" / "agents" / "agent-os").mkdir(parents=True)
        (root / ".claude" / "skills" / "deploy").mkdir(parents=True)
        (root / "src").mkdir()
        (root / "graphify-out").mkdir()
        (root / "AGENTS.md").write_text(
            "# Agent Instructions\n\nUse the filesystem MCP server and read `.agents/skills/reviewer/SKILL.md` first.\n",
            encoding="utf-8",
        )
        (root / ".agents" / "skills" / "reviewer" / "SKILL.md").write_text(
            "---\nname: reviewer\ndescription: Reviews src/app.py changes.\n---\n\n# Reviewer\n\nUse filesystem tools for `src/app.py`.\n",
            encoding="utf-8",
        )
        (root / ".claude" / "agents" / "builder" / "AGENT.md").write_text(
            "---\nname: builder\ndescription: Owns app implementation.\n---\n\n# Builder\n\nResponsible for `src/app.py`.\n",
            encoding="utf-8",
        )
        (root / ".claude" / "agents" / "agent-os" / "implementer.md").write_text(
            "---\nname: implementer\ndescription: Implements approved task lists.\n---\n\n# Implementer\n\nUse deploy skill when releasing.\n",
            encoding="utf-8",
        )
        (root / ".claude" / "skills" / "deploy" / "SKILL.md").write_text(
            "---\nname: deploy\ndescription: Deployment workflow for this repo.\n---\n\n# Deploy\n\nCheck build output before release.\n",
            encoding="utf-8",
        )
        (root / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}}}),
            encoding="utf-8",
        )
        (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (root / "graphify-out" / "graph.json").write_text(
            json.dumps({"nodes": [{"id": "code:src/app.py", "kind": "code_file", "path": "src/app.py", "label": "src/app.py"}], "edges": []}),
            encoding="utf-8",
        )
        return temp

    def test_root_skill_repo_is_detected_as_public_skill_surface(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "agents").mkdir()
        (root / "SKILL.md").write_text(
            "---\nname: agent-gps\ndescription: Build Agent GPS maps for repositories.\n---\n\n# Agent GPS\n\nMap agentic working environments.\n",
            encoding="utf-8",
        )
        (root / "agents" / "openai.yaml").write_text(
            'interface:\n  display_name: "Agent GPS"\n  short_description: "Map agent working environments."\n',
            encoding="utf-8",
        )

        graph = agent_gps.build_graph(root)

        root_skill = next(source for source in graph["sources"] if source["path"] == "SKILL.md")
        metadata = next(source for source in graph["sources"] if source["path"] == "agents/openai.yaml")
        root_skill_node = next(node for node in graph["nodes"] if node.get("path") == "SKILL.md")

        self.assertEqual(root_skill["kind"], "canonical_skill")
        self.assertEqual(root_skill["surface"], "Root skill")
        self.assertEqual(root_skill["confidence"], "high")
        self.assertEqual(metadata["kind"], "skill_metadata")
        self.assertEqual(graph["summary"]["sources"], 2)
        self.assertEqual(graph["summary"]["canonical_skills"], 1)
        self.assertEqual(graph["summary"]["skill_surfaces"], 1)
        self.assertEqual(root_skill_node["what"], "Canonical skill")
        self.assertIn("Root skill", root_skill_node["inclusion_reason"])
        self.assertTrue(any("reusable skill surface" in item for item in graph["review"]["strengths"]))

    def test_source_nodes_include_developer_facing_details(self):
        with self.make_repo() as temp:
            graph = agent_gps.build_graph(Path(temp))

        self.assertEqual(graph["schema"], "agent-gps.v2")
        skill_node = next(node for node in graph["nodes"] if node.get("path") == ".agents/skills/reviewer/SKILL.md")
        self.assertEqual(skill_node["what"], "Canonical skill")
        self.assertIn("Matched Canonical skills", skill_node["inclusion_reason"])
        self.assertIn("high-confidence", skill_node["confidence_explanation"])
        self.assertIn("Reviews src/app.py", skill_node["excerpt"])
        self.assertIn(".claude/agents/builder/AGENT.md", skill_node["read_next"])
        self.assertIn("confirmed_facts", skill_node)
        self.assertIn("inferred_links", skill_node)
        self.assertIn("connections_by_relation", skill_node)

    def test_mcp_tools_are_nodes_and_linked_from_mentions(self):
        with self.make_repo() as temp:
            graph = agent_gps.build_graph(Path(temp))

        tool = next(node for node in graph["nodes"] if node["id"] == "mcp_tool:filesystem")
        self.assertEqual(tool["kind"], "mcp_tool")
        self.assertEqual(tool["confidence"], "high")
        relations = {(edge["source"], edge["target"], edge["relation"], edge["classification"]) for edge in graph["edges"]}
        self.assertIn(("mcp_config:mcp-json", "mcp_tool:filesystem", "defines_tool", "confirmed"), relations)
        instruction_id = agent_gps.stable_node_id("instruction_doc", "AGENTS.md")
        self.assertIn((instruction_id, "mcp_tool:filesystem", "mentions_tool", "inferred"), relations)

    def test_mcp_tool_references_count_without_repo_local_server_config(self):
        with self.make_repo() as temp:
            root = Path(temp)
            (root / ".mcp.json").unlink()
            (root / ".claude" / "settings.local.json").write_text(
                json.dumps({"permissions": {"allow": ["mcp__fetch__fetch", "mcp__filesystem__read_text_file"]}}),
                encoding="utf-8",
            )
            graph = agent_gps.build_graph(root)

        self.assertEqual(graph["summary"]["mcp_server_configs"], 0)
        self.assertEqual(graph["summary"]["mcp_tool_references"], 2)
        self.assertGreaterEqual(graph["summary"]["mcp_tools"], 2)
        self.assertTrue(any(source["kind"] == "tool_permission_config" for source in graph["sources"]))
        review_text = "\n".join(graph["review"]["strengths"] + graph["review"]["weaknesses"])
        self.assertIn("MCP server/tool reference", review_text)
        self.assertIn("no repo-local MCP server config", review_text)
        self.assertNotIn("No MCP/tool config or MCP tool references were detected.", review_text)

    def test_nested_claude_agents_and_claude_skills_count_as_surfaces(self):
        with self.make_repo() as temp:
            graph = agent_gps.build_graph(Path(temp))

        self.assertGreaterEqual(graph["summary"]["agent_surfaces"], 2)
        self.assertGreaterEqual(graph["summary"]["skill_surfaces"], 2)
        self.assertTrue(any(source["path"] == ".claude/agents/agent-os/implementer.md" for source in graph["sources"]))
        review_text = "\n".join(graph["review"]["strengths"] + graph["review"]["weaknesses"])
        self.assertIn("explicit agent surface", review_text)
        self.assertIn("reusable skill surface", review_text)
        self.assertNotIn("No canonical agent surfaces were found.", review_text)

    def test_graphify_output_is_detected_and_bridged_by_path(self):
        with self.make_repo() as temp:
            graph = agent_gps.build_graph(Path(temp))

        graphify_node = next(node for node in graph["nodes"] if node.get("path") == "src/app.py" and node["kind"].startswith("graphify_"))
        self.assertEqual(graphify_node["kind"], "graphify_code")
        builder_id = agent_gps.stable_node_id("claude_agent", ".claude/agents/builder/AGENT.md")
        self.assertTrue(
            any(
                edge["source"] == builder_id
                and edge["target"] == graphify_node["id"]
                and edge["relation"] == "bridges_to_graphify"
                and edge["classification"] == "confirmed"
                for edge in graph["edges"]
            )
        )
        self.assertGreaterEqual(graph["summary"]["graphify_nodes"], 1)

    def test_report_contains_agentic_structure_review(self):
        with self.make_repo() as temp:
            root = Path(temp)
            out = root / "agent-gps-out"
            out.mkdir()
            graph = agent_gps.build_graph(root)
            agent_gps.write_report(out, graph)
            report = (out / "AGENT_GPS_REPORT.md").read_text(encoding="utf-8")

        self.assertIn("## Agentic Structure Review", report)
        self.assertIn("Overall readiness grade", report)
        self.assertIn("## Missing Owners", report)
        self.assertIn("## Suggested Improvements", report)

    def test_recommendations_propose_agent_skill_and_instruction_structure(self):
        with self.make_repo() as temp:
            root = Path(temp)
            out = root / "agent-gps-out"
            out.mkdir()
            graph = agent_gps.build_graph(root)
            agent_gps.write_recommendations(out, graph)
            recommendations = (out / "AGENT_GPS_RECOMMENDATIONS.md").read_text(encoding="utf-8")

        self.assertIn("# Agent GPS Recommendations", recommendations)
        self.assertIn("## Proposed Agents", recommendations)
        self.assertIn("builder", recommendations)
        self.assertIn("## Proposed Skills", recommendations)
        self.assertIn("reviewer", recommendations)
        self.assertIn("## Instruction Cleanup", recommendations)
        self.assertIn("## Routing Table", recommendations)
        self.assertIn("src/app.py", recommendations)

    def test_graph_includes_working_environment_action_plan(self):
        with self.make_repo() as temp:
            graph = agent_gps.build_graph(Path(temp))

        self.assertIn("review", graph)
        self.assertIn("grade", graph["review"])
        self.assertIn("action_plan", graph["review"])
        self.assertTrue(any("MCP" in item["title"] or "tool" in item["title"] for item in graph["review"]["action_plan"]))

    def test_report_and_bridge_graphify_commands_write_outputs(self):
        with self.make_repo() as temp:
            root = Path(temp)
            out = root / "agent-gps-out"
            self.assertEqual(agent_gps.command_report(Namespace(root=str(root), out=str(out))), 0)
            self.assertTrue((out / "AGENT_GPS_REPORT.md").exists())
            self.assertEqual(agent_gps.command_bridge_graphify(Namespace(root=str(root), out=str(out))), 0)
            bridge = (out / "AGENT_GPS_BRIDGE.md").read_text(encoding="utf-8")

        self.assertIn("# Agent GPS Graphify Bridge", bridge)
        self.assertIn("src/app.py", bridge)

    def test_build_writes_recommendations_artifact(self):
        with self.make_repo() as temp:
            root = Path(temp)
            out = root / "agent-gps-out"
            self.assertEqual(agent_gps.command_build(Namespace(root=str(root), out=str(out))), 0)
            recommendations = (out / "AGENT_GPS_RECOMMENDATIONS.md").read_text(encoding="utf-8")

        self.assertIn("Proposed Agents", recommendations)
        self.assertIn("Proposed Skills", recommendations)

    def test_html_selection_panel_exposes_v2_node_details(self):
        with self.make_repo() as temp:
            root = Path(temp)
            out = root / "agent-gps-out"
            out.mkdir()
            graph = agent_gps.build_graph(root)
            agent_gps.write_html(out, graph)
            html = (out / "agent-gps.html").read_text(encoding="utf-8")

        self.assertIn("Why included", html)
        self.assertIn("Why this certainty", html)
        self.assertIn("Confirmed facts", html)
        self.assertIn("Inferred links", html)
        self.assertIn("Connections by relation", html)
        self.assertIn("connections_by_relation", html)
        self.assertIn("Working Environment Review", html)
        self.assertIn("Fix first", html)
        self.assertIn("action_plan", html)
        self.assertIn("Reports", html)
        self.assertIn("Agent GPS Report", html)
        self.assertIn("Generated artifacts", html)
        self.assertIn("artifactTable", html)
        self.assertIn("Recommended Structure", html)
        self.assertIn("Proposed agents", html)
        self.assertIn("recommendations", html)
        self.assertIn("Open source", html)
        self.assertIn("Copy path", html)
        self.assertIn("Copy open command", html)
        self.assertIn("Copy brief", html)
        self.assertIn("Open paths in", html)
        self.assertIn("VS Code", html)
        self.assertIn("Cursor", html)
        self.assertIn("Windsurf", html)
        self.assertIn("editorMode", html)
        self.assertIn("openCommand", html)
        self.assertIn("pathLink", html)
        self.assertIn("data-path", html)
        self.assertNotIn('href="../', html)
        self.assertNotIn('href="AGENT_GPS_REPORT.md"', html)
        self.assertNotIn('href="AGENT_GPS_RECOMMENDATIONS.md"', html)
        self.assertNotIn('href="AGENT_GPS_BRIDGE.md"', html)
        self.assertNotIn('href="agent-gps.graph.json"', html)
        self.assertNotIn('href="manifest.json"', html)
        self.assertIn('data-tab="map"', html)
        self.assertIn('data-tab="review"', html)
        self.assertIn('data-tab="recommendations"', html)
        self.assertIn('data-tab="reports"', html)
        self.assertIn("map-workbench", html)
        self.assertNotIn("<aside", html)

    def test_html_explains_confidence_filters_in_user_language(self):
        with self.make_repo() as temp:
            root = Path(temp)
            out = root / "agent-gps-out"
            out.mkdir()
            graph = agent_gps.build_graph(root)
            agent_gps.write_html(out, graph)
            html = (out / "agent-gps.html").read_text(encoding="utf-8")

        self.assertIn("What this map means", html)
        self.assertIn("Show nodes by certainty", html)
        self.assertIn("Verified", html)
        self.assertIn("Supporting context", html)
        self.assertIn("Review first", html)
        self.assertIn('placeholder="Find node"', html)
        self.assertNotIn('placeholder="Search agents, skills, docs"', html)


if __name__ == "__main__":
    unittest.main()
