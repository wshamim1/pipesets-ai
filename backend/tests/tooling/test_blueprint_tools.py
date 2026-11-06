"""Every tool and skill the frontend's starter blueprints (frontend/src/blueprints/, one file each) put on the
canvas exists in the registry, so a cloned blueprint never holds a node the backend can't run."""
import re
from pathlib import Path

import tools
from routers.skills import BUILTIN_SKILLS

FILES = sorted((Path(__file__).resolve().parents[3] / "frontend/src/blueprints").glob("[!_]*.ts"))
SOURCE = "\n".join(f.read_text() for f in FILES if not f.name.endswith(".test.ts"))


def test_one_file_per_blueprint():
    assert sum("export const BLUEPRINT" in f.read_text() for f in FILES) == len([f for f in FILES if f.name != "index.ts" and not f.name.endswith(".test.ts")]) >= 20


def test_blueprint_tools_exist():
    ids = set(re.findall(r"toolId: '([a-z0-9_]+)'", SOURCE))
    ids |= set(re.findall(r"tool\('[^']+', \d+, \d+, '[^']*', '([a-z0-9_]+)'", SOURCE))
    ids |= {"slack_webhook"} if "slack(" in SOURCE else set()
    assert len(ids) > 20
    tools._load()
    missing = sorted(i for i in ids if tools.get_spec(i) is None)
    assert not missing, f"blueprints use unknown tools: {missing}"


def test_blueprint_skills_exist():
    skill_ids = set(re.findall(r"skill_id: '([a-z0-9_]+)'", SOURCE))
    assert skill_ids <= {s["id"] for s in BUILTIN_SKILLS}, skill_ids
