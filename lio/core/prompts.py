"""Loader for Lio's markdown prompt files."""

from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
MISSION_DIR = Path(__file__).resolve().parent.parent / "missions"
ACTIVE_MISSION = MISSION_DIR / "active.md"


def load(name: str) -> str:
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def active_mission() -> str | None:
    if ACTIVE_MISSION.exists():
        return ACTIVE_MISSION.read_text(encoding="utf-8")
    return None


def system_for(capability: str) -> str:
    parts = [load("base")]
    facts_path = PROMPT_DIR / "ashrah_facts.md"
    if facts_path.exists():
        parts.append(facts_path.read_text(encoding="utf-8"))
    mission = active_mission()
    if mission:
        parts.append("# ACTIVE MISSION CONTEXT\n\n" + mission)
    parts.append(load(capability))
    return "\n\n".join(parts)
