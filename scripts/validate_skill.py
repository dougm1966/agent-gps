from __future__ import annotations

import re
import sys
from pathlib import Path


REQUIRED = {
    "SKILL.md",
    "agent_gps.py",
    "scripts/agent_gps.py",
    "references/output-contract.md",
    "agents/openai.yaml",
}


def fail(message: str) -> int:
    print(f"validate_skill: {message}", file=sys.stderr)
    return 1


def parse_frontmatter(text: str) -> dict[str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            return None
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"\'')
    return values


def main(argv: list[str] | None = None) -> int:
    root = Path(argv[0] if argv else ".").resolve()
    missing = [path for path in sorted(REQUIRED) if not (root / path).exists()]
    if missing:
        return fail("missing required files: " + ", ".join(missing))

    skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(skill_text)
    if not frontmatter:
        return fail("SKILL.md must start with YAML frontmatter")
    if frontmatter.get("name") != "agent-gps":
        return fail("SKILL.md frontmatter name must be agent-gps")
    description = frontmatter.get("description", "")
    if len(description.split()) < 12:
        return fail("SKILL.md description is too short to trigger reliably")

    if len(skill_text.splitlines()) > 500:
        return fail("SKILL.md should stay under 500 lines for progressive disclosure")

    wrapper = (root / "scripts" / "agent_gps.py").read_text(encoding="utf-8")
    if "runpy.run_path" not in wrapper or "agent_gps.py" not in wrapper:
        return fail("scripts/agent_gps.py must delegate to the bundled scanner")

    metadata = (root / "agents" / "openai.yaml").read_text(encoding="utf-8")
    for key in ("display_name", "short_description", "default_prompt"):
        if not re.search(rf"^\s*{key}\s*:", metadata, re.M):
            return fail(f"agents/openai.yaml missing {key}")

    print("validate_skill: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
