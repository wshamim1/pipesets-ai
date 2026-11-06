"""
system.py — the server itself, for Settings → Database. Server admins only
(services/auth.is_server_admin) — a workspace owner alone isn't one.

GET  /api/system/database        — which database (type, host, name, version, size) and whether
                                   its schema is current. Never the password.
GET  /api/system/database/setup  — whether the database can be chosen from here (fresh install, and
                                   DATABASE_URL isn't set by the environment) and a pending restart
POST /api/system/database/test   — try a PostgreSQL connection
POST /api/system/database/setup  — copy this database into PostgreSQL and save DATABASE_URL in the
                                   data directory's .env; used after a restart (services/db_setup.py)
"""

from fastapi import APIRouter, HTTPException, Request

import db
from services import db_setup
from services.acl import require_server_admin
from services.db_copy import CopyError
from services.request_context import get_request_context

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/database")
def database(request: Request):
    require_server_admin(get_request_context(request))
    return db.database_info()


@router.get("/database/setup")
def database_setup_status(request: Request):
    require_server_admin(get_request_context(request))
    return db_setup.status()


@router.post("/database/test")
def database_test(target: db_setup.PostgresTarget, request: Request):
    require_server_admin(get_request_context(request))
    return db_setup.test_connection(target)


@router.post("/database/setup")
def database_setup(target: db_setup.PostgresTarget, request: Request):
    require_server_admin(get_request_context(request))
    try:
        return db_setup.apply(target)
    except CopyError as e:
        raise HTTPException(status_code=409, detail=str(e))
