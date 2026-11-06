"""Dictionary — built-in tool `dictionary`."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, params

TOOL = ToolSpec(
    id="dictionary",
    name="Dictionary",
    icon="📖",
    category="Research & Knowledge",
    description="Definitions, pronunciation, examples and synonyms for a word (free, no key).",
    default_config={"language": "en"},
    order=70,
    selects={
        "language": Select("Language", (("en", "English"),), hint="The free dictionary API covers English."),
    },
    parameters=params({"word": {"type": "string", "description": "The word to look up"}}),
    input_param="word",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    word = inp.split()[0] if inp else ""
    if not word:
        return "[Dictionary] Please provide a word."
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://api.dictionaryapi.dev/api/v2/entries/{cfg.get('language', 'en')}/{word}")
        if resp.status_code == 404:
            return f"[Dictionary] No definition found for '{word}'."
        resp.raise_for_status()
        entry = resp.json()[0]
        lines = [f"[Dictionary: {entry.get('word', word)}] {entry.get('phonetic', '')}".rstrip()]
        for meaning in entry.get("meanings", [])[:4]:
            lines.append(f"\n{meaning.get('partOfSpeech', '')}:")
            for d in meaning.get("definitions", [])[:3]:
                lines.append(f"  - {d.get('definition', '')}" + (f"  e.g. \"{d['example']}\"" if d.get("example") else ""))
            if meaning.get("synonyms"):
                lines.append(f"  synonyms: {', '.join(meaning['synonyms'][:6])}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Dictionary] Error: {e}"
