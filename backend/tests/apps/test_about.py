"""About (GET /api/about): version and commit, Python and backend libraries at their installed versions, the
database type without its address or credentials, and the built-in catalog counts."""
import json
from importlib import metadata

import main
from helpers import hdr
from version import APP_VERSION


def test_about(client):
    r = client.get("/api/about", headers=hdr("user_viewer", "proj_support"))
    assert r.status_code == 200, "any signed-in user"
    a = r.json()
    assert a["app"]["version"] == APP_VERSION == main.app.version and a["app"]["license"] == "Apache-2.0"
    libs = {l["name"]: l["version"] for l in a["backend"]["libraries"]}
    assert libs["FastAPI"] == metadata.version("fastapi") and libs["SQLAlchemy"] == metadata.version("sqlalchemy")
    assert a["backend"]["python"].count(".") == 2
    assert a["backend"]["database"]["type"] in ("sqlite", "postgresql")
    assert set(a["backend"]["database"]) == {"type", "driver", "version"}, "no host, name or URL"
    assert "password" not in json.dumps(a).lower()
    c = a["catalog"]
    assert c["tools"] > 100 and c["mcp_servers"] > 50 and c["agents"] >= 20 and c["starter_roles"] == 14


def test_about_needs_sign_in(client, env):
    env.setenv("AUTH_MODE", "session")
    assert client.get("/api/about").status_code == 401
