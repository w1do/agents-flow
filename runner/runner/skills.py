"""Read inline stage skill snapshots, never files from workflow/skills."""

import re

from .errors import RunnerError


def category(skill):
    name = skill.get("filename") or skill.get("name") or ""
    raw = skill.get("category") or name.split("--", 1)[0]
    return re.sub(r"[\s_]+", "-", raw.strip().lower())


def validate_skills(skills, stage):
    if not isinstance(skills, list):
        raise RunnerError("skills must be an array")
    for skill in skills:
        if not isinstance(skill, dict) or not isinstance(skill.get("content"), str):
            raise RunnerError("Each skill must contain inline text content")
        if any(not isinstance(skill.get(k, ""), str) for k in ("category", "filename", "name")):
            raise RunnerError("Skill metadata must be text")
        kind = category(skill)
        publication = kind.startswith(("git", "deploy", "деплой", "публикац"))
        if publication != (stage == "publication"):
            raise RunnerError("Skill does not belong to this stage")
        if stage == "testing" and kind not in {"test", "testing"} and not kind.startswith("тест"):
            raise RunnerError("Only testing skills are accepted during testing")
    return skills


def commands(skills):
    """Executable skill blocks are one shell program each; plain prose is ignored."""
    result = []
    for skill in skills:
        content = skill["content"]
        blocks = re.findall(r"^```([^\s`]*)[^\n]*\n(.*?)^```\s*$", content, re.M | re.S)
        for language, block in blocks:
            lines = [line[2:] if line.startswith("$ ") else line for line in block.splitlines()]
            command = "\n".join(lines).strip()
            if command:
                result.append((language.lower(), command))
    return result
