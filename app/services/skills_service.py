"""
app/services/skills_service.py

Agent Skills system for Motivi-AI.

Skills are .md files in app/skills/ with YAML-like frontmatter:

    ---
    name: word-document
    description: Create Word (.docx) documents...
    ---

    # Word Document Creation
    ... full instructions ...

Progressive loading (mirrors Claude Agent Skills architecture):
  Level 1 — metadata (name + description) is appended to the system prompt every turn.
             Cost: ~80 tokens per skill, paid once.
  Level 2 — full instructions are loaded only when the LLM calls load_skill(name).
             Cost: 300–1500 tokens, paid only when the skill is actually needed.

The LLM sees available skills listed in the system prompt and decides when to call load_skill.
After loading, the instructions enter the context and guide the LLM's next tool calls.
"""
from __future__ import annotations

from pathlib import Path
from loguru import logger

SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillsService:
    """Stateless service for loading Agent Skills from the filesystem."""

    # Metadata is cached after first load (files don't change at runtime)
    _metadata_cache: list[dict] | None = None

    @classmethod
    def _parse_frontmatter(cls, content: str) -> tuple[dict, str]:
        """
        Parse simple YAML-like frontmatter.

        Expected format:
            ---
            name: skill-name
            description: One-line description
            ---
            # Body content...

        Returns (meta dict, body string).
        """
        if not content.startswith("---"):
            return {}, content

        # Find the closing ---
        end = content.find("\n---", 3)
        if end == -1:
            return {}, content

        frontmatter_text = content[3:end].strip()
        body = content[end + 4:].strip()

        meta: dict[str, str] = {}
        for line in frontmatter_text.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip()

        return meta, body

    @classmethod
    def get_all_metadata(cls) -> list[dict]:
        """
        Load name + description from every skill file.
        Result is cached — safe to call every request.
        """
        if cls._metadata_cache is not None:
            return cls._metadata_cache

        skills: list[dict] = []
        if not SKILLS_DIR.exists():
            cls._metadata_cache = skills
            return skills

        for skill_file in sorted(SKILLS_DIR.glob("*.md")):
            try:
                content = skill_file.read_text(encoding="utf-8")
                meta, _ = cls._parse_frontmatter(content)
                if "name" in meta and "description" in meta:
                    skills.append({"name": meta["name"], "description": meta["description"]})
            except Exception as e:
                logger.warning("Failed to load skill metadata from {}: {}", skill_file.name, e)

        cls._metadata_cache = skills
        logger.info("Loaded {} skill(s) metadata from {}", len(skills), SKILLS_DIR)
        return skills

    @classmethod
    def get_skill_content(cls, name: str) -> str | None:
        """
        Load and return the full instructions body for the skill with the given name.
        Returns None if not found.
        """
        if not SKILLS_DIR.exists():
            return None

        for skill_file in sorted(SKILLS_DIR.glob("*.md")):
            try:
                content = skill_file.read_text(encoding="utf-8")
                meta, body = cls._parse_frontmatter(content)
                if meta.get("name") == name:
                    logger.info("Loaded skill content: {} ({} chars)", name, len(body))
                    return body
            except Exception as e:
                logger.warning("Failed to read skill file {}: {}", skill_file.name, e)

        return None

    @classmethod
    def get_available_names(cls) -> list[str]:
        """Return sorted list of available skill names."""
        return [s["name"] for s in cls.get_all_metadata()]

    @classmethod
    def get_skills_prompt_snippet(cls) -> str:
        """
        Build the system prompt block that lists available skills.
        Appended to the persona prompt so the LLM knows what to call.
        Returns empty string if no skills are installed.
        """
        metadata = cls.get_all_metadata()
        if not metadata:
            return ""

        lines = [
            "\n\n## Available Skills",
            (
                "You have access to specialist skill instructions. "
                "When the user requests a task that matches a skill below, call `load_skill(name)` "
                "FIRST to load step-by-step instructions, then use those instructions to complete the task. "
                "Do not attempt the task from memory — always load the skill first."
            ),
            "",
        ]
        for skill in metadata:
            lines.append(f"- **{skill['name']}**: {skill['description']}")

        return "\n".join(lines)
