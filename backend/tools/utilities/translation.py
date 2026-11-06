"""Translation — built-in tool `translation` (DeepL API key, or the free LibreTranslate service)."""

from typing import Any, Dict, Optional

import httpx

from tools.base import Select, ToolSpec, enum, params
from tools._choices import LANGUAGES

LABEL = "[Translation]"
DEEPL_URL = "https://api-free.deepl.com/v2/translate"
LIBRE_URL = "https://api.libretranslate.com/translate"
_SOURCE_CODES = tuple(code for code, _name in LANGUAGES)          # includes "auto"
_TARGET_CODES = tuple(code for code, _name in LANGUAGES if code != "auto")
_TARGETS = tuple((code, name) for code, name in LANGUAGES if code != "auto")


TOOL = ToolSpec(
    id="translation",
    name="Translation",
    icon="🌐",
    category="Everyday Utilities",
    description="Translates text between languages. DeepL with an API key, or the free LibreTranslate "
                "service; the source language auto-detects when set to auto.",
    default_config={"api_key": "", "source": "auto", "target": "en"},
    order=30,
    selects={
        "source": Select("Source language", LANGUAGES,
                         hint="Which language the text is in; 'Auto-detect' lets the service figure it out."),
        "target": Select("Target language", _TARGETS, hint="Language to translate the text into."),
    },
    parameters=params(
        {"text": {"type": "string", "description": "The text to translate"}},
        {
            "source": enum(_SOURCE_CODES, "Source language code, or 'auto' to detect it"),
            "target": enum(_TARGET_CODES, "Target language code"),
        },
    ),
    input_param="text",
)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text = (inp or "").strip()
    if not text:
        return f"{LABEL} Please provide the text to translate as input."

    source = str(cfg.get("source") or "auto").strip().lower()
    target = str(cfg.get("target") or "en").strip().lower()
    api_key = (cfg.get("api_key") or "").strip()

    try:
        if api_key:
            async with httpx.AsyncClient(timeout=20.0) as client:
                payload: Dict[str, Any] = {"auth_key": api_key, "text": [text], "target_lang": target.upper()}
                if source and source != "auto":
                    payload["source_lang"] = source.upper()
                resp = await client.post(DEEPL_URL, json=payload)
                resp.raise_for_status()
                out = (resp.json().get("translations") or [{}])[0].get("text") or ""
        else:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(LIBRE_URL, json={"q": text, "source": source, "target": target})
                resp.raise_for_status()
                out = resp.json().get("translatedText") or ""
    except Exception as e:
        return f"{LABEL} Error: {e}"

    out = (out or "").strip()
    if not out:
        return f"{LABEL} The translation came back empty."
    return f"{LABEL} {source} → {target}\n{out}"
