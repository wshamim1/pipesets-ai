"""XML ↔ JSON converter — built-in tool `xml_converter` (offline, standard library).

XML input becomes JSON: attributes as ``@name``, text as ``#text`` when an element also has
attributes or children, and repeated child tags as lists. JSON input (one top-level key, or
``root_tag`` to wrap it) becomes indented XML. Documents with a DOCTYPE or entity declarations
are refused, so entity-expansion and external-entity tricks never reach the parser.
"""

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from tools.base import Select, ToolSpec, enum, params

LABEL = "[XML Converter]"
MAX_INPUT = 2_000_000
_DECLARATIONS = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.I)
_TAG_OK = re.compile(r"^[A-Za-z_][\w.-]*$")

TOOL = ToolSpec(
    id="xml_converter",
    name="XML ↔ JSON Converter",
    icon="🧾",
    category="Data & Files",
    description="Converts XML to JSON (attributes as @name, repeated tags as lists) or JSON to XML. Direction is detected from the input.",
    default_config={"direction": "auto", "root_tag": "root"},
    order=430,
    selects={"direction": Select("Direction", (("auto", "Auto-detect"), ("xml_to_json", "XML → JSON"),
                                               ("json_to_xml", "JSON → XML")))},
    parameters=params(
        {"data": {"type": "string", "description": "The XML document or JSON text to convert"}},
        {"direction": enum(["auto", "xml_to_json", "json_to_xml"], "Conversion direction (auto detects it)")},
    ),
    input_param="data",
)


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _to_obj(el: ET.Element) -> Any:
    out: Dict[str, Any] = {f"@{_local(k)}": v for k, v in el.attrib.items()}
    for child in el:
        key, value = _local(child.tag), _to_obj(child)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(value)
        else:
            out[key] = value
    text = (el.text or "").strip()
    if not out:
        return text
    if text:
        out["#text"] = text
    return out


def _build(parent: ET.Element, tag: str, value: Any) -> None:
    if not _TAG_OK.match(tag):
        raise ValueError(f"'{tag}' isn't a valid XML tag name")
    if isinstance(value, list):
        for item in value:
            _build(parent, tag, item)
        return
    el = ET.SubElement(parent, tag)
    if isinstance(value, dict):
        for k, v in value.items():
            if k.startswith("@"):
                el.set(k[1:], "" if v is None else str(v))
            elif k == "#text":
                el.text = "" if v is None else str(v)
            else:
                _build(el, k, v)
    elif value is not None:
        el.text = str(value).lower() if isinstance(value, bool) else str(value)


async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> Optional[str]:
    text = inp.strip()
    if not text:
        return f"{LABEL} Provide an XML document or JSON to convert."
    if len(text) > MAX_INPUT:
        return f"{LABEL} Input is too large ({len(text):,} characters; the limit is {MAX_INPUT:,})."
    direction = cfg.get("direction") or "auto"
    if direction == "auto":
        direction = "xml_to_json" if text.startswith("<") else "json_to_xml"

    if direction == "xml_to_json":
        if _DECLARATIONS.search(text):
            return f"{LABEL} DOCTYPE and ENTITY declarations aren't supported — remove them and try again."
        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            return f"{LABEL} Invalid XML: {e}"
        try:
            return json.dumps({_local(root.tag): _to_obj(root)}, indent=2, ensure_ascii=False)
        except RecursionError:
            return f"{LABEL} The XML is nested too deeply to convert."

    if direction != "json_to_xml":
        return f"{LABEL} Direction is auto, xml_to_json or json_to_xml — got '{direction}'."
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return f"{LABEL} Invalid JSON: {e}"
    except RecursionError:
        return f"{LABEL} The JSON is nested too deeply to convert."
    if isinstance(data, dict) and len(data) == 1 and not next(iter(data)).startswith(("@", "#")):
        tag, value = next(iter(data.items()))
    else:
        tag, value = (cfg.get("root_tag") or "root").strip(), data
    holder = ET.Element("holder")
    try:
        if isinstance(value, list):
            value = {"item": value}
        _build(holder, tag, value)
    except ValueError as e:
        return f"{LABEL} {e}"
    except RecursionError:
        return f"{LABEL} The JSON is nested too deeply to convert."
    root = holder[0]
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")
