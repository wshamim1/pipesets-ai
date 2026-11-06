"""
lab.py  —  Research Lab API

Endpoints
---------
POST /api/lab/postgres/start     — spin up a Postgres container (Docker or Podman)
POST /api/lab/postgres/stop      — stop & remove the container
GET  /api/lab/postgres/status    — container running state + DSN
POST /api/lab/postgres/exec      — execute arbitrary SQL (schema + DML)
POST /api/lab/postgres/seed      — seed a preset dataset into the running DB

GET  /api/lab/services/catalog   — supported service containers (mysql, mariadb, mongodb, clickhouse, chroma, ...)
POST /api/lab/services/start     — start a service container (Docker or Podman)
POST /api/lab/services/stop      — stop & remove a service container
POST /api/lab/services/seed      — seed a sample dataset into a MySQL / MariaDB / MongoDB container
GET  /api/lab/services/status    — tracked service containers + running state
GET  /api/lab/services/logs      — tail container logs

POST /api/lab/pdf/generate       — generate a PDF from text / template
POST /api/lab/pdf/batch          — generate multiple PDFs in one call

GET  /api/lab/ollama/list        — list locally installed Ollama models
POST /api/lab/ollama/pull        — pull a model (SSE stream of progress)
DELETE /api/lab/ollama/{name}    — remove a locally installed model

GET  /api/lab/llamacpp/status     — llama-server health, loaded model and context size
GET  /api/lab/llamacpp/setup      — installed binary, available installers / runtimes, managed servers
POST /api/lab/llamacpp/install    — install via brew / winget, or pull the server image (SSE output)
POST /api/lab/llamacpp/start      — start a llama-server (native process or container)
POST /api/lab/llamacpp/stop       — stop a managed llama-server by port
GET  /api/lab/llamacpp/logs       — tail a managed llama-server's output

GET  /api/lab/jan/setup           — whether the Jan desktop app is installed + available installers
POST /api/lab/jan/install         — install Jan via Homebrew cask (SSE output)
POST /api/lab/jan/open            — launch the Jan desktop app
POST /api/lab/jan/status          — probe Jan's local API server (models, auth)

GET  /api/lab/status             — overall lab environment status
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import platform
import tempfile
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("pipesets-ai-backend")

router = APIRouter(prefix="/api/lab", tags=["lab"])

# ── Shared state (in-process; resets on restart) ──────────────────────────────
_pg_container: Dict[str, Any] = {}   # name, port, dsn, started_at, runtime


# ── Models ────────────────────────────────────────────────────────────────────

class PostgresStartRequest(BaseModel):
    container_name: str = Field(default="lab-postgres", description="Container name")
    image: str = Field(default="postgres:16-alpine", description="Docker/Podman image")
    port: int = Field(default=5433, description="Host port to bind (5433 avoids conflicts with local Postgres)")
    db_name: str = Field(default="labdb")
    db_user: str = Field(default="labuser")
    db_password: str = Field(default="labpass")
    runtime: str = Field(default="auto", description="auto | docker | podman | kubernetes")


class SqlExecRequest(BaseModel):
    sql: str = Field(..., description="SQL statement(s) to execute")
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    port: Optional[int] = None


class SeedRequest(BaseModel):
    dataset: str = Field(default="ecommerce", description="ecommerce | hr | crm | custom")
    custom_ddl: Optional[str] = Field(default=None, description="Custom DDL+INSERT SQL for 'custom' dataset")
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    port: Optional[int] = None


class PdfGenerateRequest(BaseModel):
    title: str = Field(default="Lab Test Document")
    content: str = Field(..., description="Text content for the PDF")
    output_path: str = Field(default="", description="Save path. Leave blank to use a temp file.")
    template: str = Field(default="plain", description="plain | report | bio | invoice")
    author: str = Field(default="Research Lab")


class PdfBatchRequest(BaseModel):
    documents: List[PdfGenerateRequest]
    output_dir: str = Field(default="", description="Directory to save all PDFs")


# ── Runtime detection ─────────────────────────────────────────────────────────

_RUNTIMES = ("docker", "podman", "kubernetes")
_RUNTIME_HINTS = {
    "docker": "Start Docker Desktop (or the docker daemon).",
    "podman": "Run 'podman machine init' (first time) and 'podman machine start'.",
    "kubernetes": "Check your kubeconfig / cluster (e.g. minikube start, kind, or Docker Desktop Kubernetes).",
}

# kubectl port-forward processes, keyed by pod name (kubernetes runtime only)
_port_forwards: Dict[str, "subprocess.Popen[bytes]"] = {}


def _run(cmd: List[str], timeout: int = 60, input_text: Optional[str] = None) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return 1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return 1, "", str(e)


def _rt_bin(rt: str) -> str:
    return "kubectl" if rt == "kubernetes" else rt


def _runtime_problem(rt: str) -> Optional[str]:
    """Return a human-readable reason the runtime can't be used, or None if it's ready."""
    binary = _rt_bin(rt)
    if shutil.which(binary) is None:
        return f"'{binary}' is not installed or not on the backend's PATH."
    probe = [binary, "cluster-info"] if rt == "kubernetes" else [binary, "info"]
    if _run(probe, timeout=8)[0] != 0:
        return f"{rt} is installed but not reachable. {_RUNTIME_HINTS[rt]}"
    return None


def _resolve_runtime(preference: str = "auto") -> tuple[Optional[str], Optional[str]]:
    """Return (runtime, error). 'auto' tries docker then podman (never silently picks kubernetes)."""
    if preference in _RUNTIMES:
        problem = _runtime_problem(preference)
        return (None, problem) if problem else (preference, None)
    for rt in ("docker", "podman"):
        if _runtime_problem(rt) is None:
            return rt, None
    return None, "No container runtime available. Start Podman or Docker, or choose Kubernetes."


def _stop_forward(name: str) -> None:
    proc = _port_forwards.pop(name, None)
    if proc and proc.poll() is None:
        proc.terminate()


def _rt_rm(rt: str, name: str) -> tuple[int, str, str]:
    """Remove a container / pod (ignores 'not found')."""
    if rt == "kubernetes":
        _stop_forward(name)
        return _run(["kubectl", "delete", "pod", name, "--ignore-not-found", "--force", "--grace-period=0"], timeout=60)
    return _run([rt, "rm", "-f", name])


def _rt_run(rt: str, name: str, image: str, ports: List[tuple[int, int]],
            env: Dict[str, str], args: List[str], timeout: int = 300) -> tuple[int, str, str]:
    """Start a container (docker/podman) or a pod + port-forward (kubernetes). ports = [(host, container)]."""
    if rt == "kubernetes":
        cmd = ["kubectl", "run", name, f"--image={image}", "--restart=Never"]
        if ports:
            cmd.append(f"--port={ports[0][1]}")
        cmd += [f"--env={k}={v}" for k, v in env.items()]
        if args:
            cmd += ["--", *args]
        rc, out, err = _run(cmd, timeout=60)
        if rc != 0:
            return rc, out, err
        rc, out, err = _run(["kubectl", "wait", "--for=condition=Ready", f"pod/{name}", "--timeout=300s"], timeout=timeout + 10)
        if rc != 0:
            return rc, "", err or out
        fwd = ["kubectl", "port-forward", f"pod/{name}", *[f"{h}:{c}" for h, c in ports]]
        _port_forwards[name] = subprocess.Popen(fwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0, name, ""

    cmd = [rt, "run", "-d", "--name", name]
    for h, c in ports:
        cmd += ["-p", f"{h}:{c}"]
    for k, v in env.items():
        cmd += ["-e", f"{k}={v}"]
    cmd.append(image)
    cmd += args
    return _run(cmd, timeout=timeout)


def _rt_exec_cmd(rt: str, name: str, args: List[str], interactive: bool = False) -> List[str]:
    base = ["kubectl", "exec"] if rt == "kubernetes" else [rt, "exec"]
    if interactive:
        base.append("-i")
    return [*base, name, "--", *args] if rt == "kubernetes" else [*base, name, *args]


def _rt_running(rt: str, name: str) -> bool:
    if rt == "kubernetes":
        rc, out, _ = _run(["kubectl", "get", "pod", name, "-o", "jsonpath={.status.phase}"])
        return rc == 0 and out == "Running"
    rc, out, _ = _run([rt, "inspect", "--format", "{{.State.Running}}", name])
    return rc == 0 and "true" in out.lower()


# ── Re-adopt containers after a backend restart ───────────────────────────────
# _pg_container / _svc_containers live in memory, but the containers outlive the
# backend. On first use after a restart, find running lab-* containers on
# docker/podman and rebuild their entries (credentials come from the container env).

_recovered = False


def _running_lab_containers() -> Dict[str, tuple[str, Dict[str, Any]]]:
    """container name -> (runtime, inspect info) for running lab-* containers."""
    found: Dict[str, tuple[str, Dict[str, Any]]] = {}
    for rt in ("docker", "podman"):
        if shutil.which(rt) is None:
            continue
        rc, out, _ = _run([rt, "ps", "--filter", "name=lab-", "--format", "{{.Names}}"], timeout=10)
        names = [n for n in out.split() if n.startswith("lab-") and n not in found] if rc == 0 else []
        if not names:
            continue
        rc, out, _ = _run([rt, "inspect", *names], timeout=15)
        try:
            infos = json.loads(out) if rc == 0 else []
        except json.JSONDecodeError:
            infos = []
        for info in infos:
            name = (info.get("Name") or "").lstrip("/")
            if name and (info.get("State") or {}).get("Running"):
                found[name] = (rt, info)
    return found


def _host_port(info: Dict[str, Any], container_port: int) -> Optional[int]:
    bindings = ((info.get("NetworkSettings") or {}).get("Ports") or {}).get(f"{container_port}/tcp") or []
    for b in bindings:
        if b.get("HostPort"):
            return int(b["HostPort"])
    return None


def _container_env(info: Dict[str, Any]) -> Dict[str, str]:
    return dict(e.split("=", 1) for e in (info.get("Config") or {}).get("Env") or [] if "=" in e)


def _recover_tracked() -> None:
    global _recovered, _pg_container
    if _recovered:
        return
    _recovered = True
    try:
        found = _running_lab_containers()
    except Exception as e:   # never let recovery break the Lab endpoints
        logger.warning(f"Lab: could not look for running containers: {e}")
        return

    pg = found.get("lab-postgres")
    if pg and not _pg_container:
        rt, info = pg
        env = _container_env(info)
        port = _host_port(info, 5432) or 5433
        db_name, db_user = env.get("POSTGRES_DB", "labdb"), env.get("POSTGRES_USER", "labuser")
        db_password = env.get("POSTGRES_PASSWORD", "")
        _pg_container = {
            "container_name": "lab-postgres",
            "container_id": (info.get("Id") or "")[:12],
            "image": (info.get("Config") or {}).get("Image", ""),
            "port": port,
            "db_name": db_name,
            "db_user": db_user,
            "db_password": db_password,
            "dsn": f"postgresql://{db_user}:{db_password}@localhost:{port}/{db_name}",
            "runtime": rt,
            "started_at": (info.get("State") or {}).get("StartedAt", ""),
            "ready": True,
        }
        logger.info(f"Lab: re-adopted running container 'lab-postgres' ({rt}, port {port})")

    for key, spec in _SERVICES.items():
        name = f"lab-{key}"
        if name not in found or name in _svc_containers:
            continue
        rt, info = found[name]
        env = _container_env(info)
        ctx: Dict[str, Any] = {k: spec.get(k, "") for k in ("user", "password", "database")}
        for env_key, tpl in spec.get("env", {}).items():   # "{password}" templates map env back to fields
            m = re.fullmatch(r"\{(\w+)\}", tpl)
            if m and env_key in env:
                ctx[m.group(1)] = env[env_key]
        ctx["port"] = _host_port(info, spec["container_port"]) or spec["host_port"]
        try:
            conn = spec["conn"].format(**ctx)
        except (KeyError, IndexError):
            conn = ""
        _svc_containers[name] = {
            "container_name": name,
            "service": key,
            "container_id": (info.get("Id") or "")[:12],
            "image": (info.get("Config") or {}).get("Image", ""),
            "port": ctx["port"],
            "runtime": rt,
            "started_at": (info.get("State") or {}).get("StartedAt", ""),
            "ready": True,
            "conn": conn.replace(str(ctx["password"]), "***") if ctx["password"] else conn,
        }
        _svc_auth[name] = {k: str(ctx[k]) for k in ("user", "password", "database")}
        logger.info(f"Lab: re-adopted running container '{name}' ({rt}, port {ctx['port']})")


def _rt_logs(rt: str, name: str, tail: int) -> tuple[int, str, str]:
    if rt == "kubernetes":
        return _run(["kubectl", "logs", f"--tail={tail}", name])
    return _run([rt, "logs", "--tail", str(tail), name])


# ── Postgres helpers ──────────────────────────────────────────────────────────

def _pg_connect(port: int, db_name: str, db_user: str, db_password: str):
    import psycopg2
    return psycopg2.connect(
        host="localhost",
        port=port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        connect_timeout=10,
    )


def _wait_for_postgres(port: int, db_name: str, db_user: str, db_password: str, timeout: int = 30) -> bool:
    """Poll until Postgres is ready or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = _pg_connect(port, db_name, db_user, db_password)
            conn.close()
            return True
        except Exception:
            time.sleep(1)
    return False


# ── Preset datasets ───────────────────────────────────────────────────────────

_DATASETS: Dict[str, str] = {
    "ecommerce": """
-- E-Commerce dataset for agentic testing
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(120) NOT NULL,
    email       VARCHAR(200) UNIQUE NOT NULL,
    city        VARCHAR(80),
    country     VARCHAR(60) DEFAULT 'US',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    category    VARCHAR(80),
    price       NUMERIC(10,2) NOT NULL,
    stock       INTEGER DEFAULT 0
);

CREATE TABLE orders (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    status      VARCHAR(30) DEFAULT 'pending',
    total       NUMERIC(10,2),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE order_items (
    id          SERIAL PRIMARY KEY,
    order_id    INTEGER REFERENCES orders(id),
    product_id  INTEGER REFERENCES products(id),
    quantity    INTEGER NOT NULL,
    unit_price  NUMERIC(10,2) NOT NULL
);

INSERT INTO customers (name, email, city, country) VALUES
  ('Alice Johnson', 'alice@example.com', 'New York', 'US'),
  ('Bob Smith',     'bob@example.com',   'London',   'GB'),
  ('Carol White',   'carol@example.com', 'Toronto',  'CA'),
  ('David Kim',     'david@example.com', 'Seoul',    'KR'),
  ('Emma Brown',    'emma@example.com',  'Berlin',   'DE');

INSERT INTO products (name, category, price, stock) VALUES
  ('Laptop Pro 15',   'Electronics', 1299.99, 45),
  ('Wireless Mouse',  'Electronics',   29.99, 200),
  ('USB-C Hub',       'Electronics',   49.99, 150),
  ('Standing Desk',   'Furniture',    399.99, 20),
  ('Office Chair',    'Furniture',    249.99, 35),
  ('Python Handbook', 'Books',         39.99, 80),
  ('AI Primer',       'Books',         34.99, 120);

INSERT INTO orders (customer_id, status, total, created_at) VALUES
  (1, 'completed', 1329.98, NOW() - INTERVAL '10 days'),
  (2, 'completed',   79.98, NOW() - INTERVAL '7 days'),
  (3, 'shipped',    399.99, NOW() - INTERVAL '3 days'),
  (4, 'pending',     74.98, NOW() - INTERVAL '1 day'),
  (1, 'completed',  249.99, NOW() - INTERVAL '5 days');

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  (1, 1, 1, 1299.99), (1, 2, 1, 29.99),
  (2, 2, 1, 29.99),   (2, 3, 1, 49.99),
  (3, 4, 1, 399.99),
  (4, 6, 1, 39.99),   (4, 7, 1, 34.99),
  (5, 5, 1, 249.99);
""",

    "hr": """
-- HR / Employee dataset for agentic testing
DROP TABLE IF EXISTS performance_reviews CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS departments CASCADE;

CREATE TABLE departments (
    id    SERIAL PRIMARY KEY,
    name  VARCHAR(100) NOT NULL,
    budget NUMERIC(12,2)
);

CREATE TABLE employees (
    id            SERIAL PRIMARY KEY,
    first_name    VARCHAR(60) NOT NULL,
    last_name     VARCHAR(60) NOT NULL,
    email         VARCHAR(200) UNIQUE NOT NULL,
    department_id INTEGER REFERENCES departments(id),
    title         VARCHAR(100),
    salary        NUMERIC(10,2),
    hired_at      DATE,
    active        BOOLEAN DEFAULT TRUE
);

CREATE TABLE performance_reviews (
    id          SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES employees(id),
    reviewer    VARCHAR(120),
    score       INTEGER CHECK (score BETWEEN 1 AND 5),
    notes       TEXT,
    reviewed_at DATE DEFAULT CURRENT_DATE
);

INSERT INTO departments (name, budget) VALUES
  ('Engineering', 2500000),
  ('Data Science', 1800000),
  ('Product',      900000),
  ('Marketing',    600000);

INSERT INTO employees (first_name, last_name, email, department_id, title, salary, hired_at) VALUES
  ('Alice',  'Park',    'alice.park@corp.com',   1, 'Senior Engineer',     120000, '2021-03-15'),
  ('Ben',    'Clarke',  'ben.clarke@corp.com',   1, 'Staff Engineer',      145000, '2019-07-01'),
  ('Carol',  'Nguyen',  'carol.n@corp.com',      2, 'ML Engineer',         135000, '2022-01-10'),
  ('David',  'Santos',  'david.s@corp.com',      2, 'Data Scientist',      118000, '2020-11-20'),
  ('Emma',   'Wilson',  'emma.w@corp.com',       3, 'Product Manager',     115000, '2021-06-05'),
  ('Frank',  'Lee',     'frank.lee@corp.com',    4, 'Marketing Lead',       95000, '2020-02-14');

INSERT INTO performance_reviews (employee_id, reviewer, score, notes, reviewed_at) VALUES
  (1, 'Ben Clarke',   5, 'Exceptional delivery on Q3 platform migration.',  '2024-01-15'),
  (2, 'VP Eng',       4, 'Strong technical leadership, good mentoring.',    '2024-01-15'),
  (3, 'Carol Nguyen', 5, 'Built the entire recommendation model.',          '2024-01-16'),
  (4, 'Carol Nguyen', 3, 'Good work but missed two sprint deadlines.',      '2024-01-16'),
  (5, 'CEO',          4, 'Roadmap quality improved significantly.',         '2024-01-17');
""",

    "crm": """
-- CRM / Sales pipeline dataset for agentic testing
DROP TABLE IF EXISTS activities CASCADE;
DROP TABLE IF EXISTS deals CASCADE;
DROP TABLE IF EXISTS contacts CASCADE;
DROP TABLE IF EXISTS companies CASCADE;

CREATE TABLE companies (
    id       SERIAL PRIMARY KEY,
    name     VARCHAR(200) NOT NULL,
    industry VARCHAR(80),
    size     VARCHAR(30)
);

CREATE TABLE contacts (
    id         SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id),
    name       VARCHAR(120) NOT NULL,
    email      VARCHAR(200),
    role       VARCHAR(80)
);

CREATE TABLE deals (
    id         SERIAL PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts(id),
    title      VARCHAR(200),
    stage      VARCHAR(40) DEFAULT 'prospecting',
    value      NUMERIC(12,2),
    close_date DATE,
    owner      VARCHAR(80)
);

CREATE TABLE activities (
    id         SERIAL PRIMARY KEY,
    deal_id    INTEGER REFERENCES deals(id),
    type       VARCHAR(40),
    notes      TEXT,
    logged_at  TIMESTAMP DEFAULT NOW()
);

INSERT INTO companies (name, industry, size) VALUES
  ('Acme Corp',      'Manufacturing', 'Enterprise'),
  ('Startup XYZ',    'SaaS',          'SMB'),
  ('Global Finance', 'Finance',       'Enterprise'),
  ('Tech Ventures',  'Technology',    'Mid-Market');

INSERT INTO contacts (company_id, name, email, role) VALUES
  (1, 'John Doe',    'john@acme.com',    'CTO'),
  (2, 'Jane Roe',    'jane@startup.com', 'CEO'),
  (3, 'Mike Fin',    'mike@gf.com',      'VP Finance'),
  (4, 'Sara Tech',   'sara@tv.com',      'Head of IT');

INSERT INTO deals (contact_id, title, stage, value, close_date, owner) VALUES
  (1, 'Platform Upgrade',     'negotiation', 250000, '2024-09-30', 'Alice'),
  (2, 'Annual SaaS License',  'proposal',     48000, '2024-08-15', 'Bob'),
  (3, 'Data Analytics Suite', 'closed_won',  180000, '2024-07-01', 'Alice'),
  (4, 'Security Audit',       'prospecting',  35000, '2024-10-31', 'Carol');

INSERT INTO activities (deal_id, type, notes) VALUES
  (1, 'call',    'Discussed migration timeline and budget approval.'),
  (1, 'email',   'Sent updated proposal with Q4 pricing.'),
  (2, 'meeting', 'Demo of new analytics dashboard — very positive.'),
  (3, 'call',    'Contract signed. Kickoff scheduled for Aug 5.'),
  (4, 'email',   'Initial outreach — awaiting response.');
""",
}


# ── Postgres endpoints ────────────────────────────────────────────────────────

@router.post("/postgres/start")
def postgres_start(req: PostgresStartRequest):
    global _pg_container
    runtime, problem = _resolve_runtime(req.runtime)
    if problem:
        return {"success": False, "error": problem, "runtime": req.runtime}

    # Stop existing container with same name if any
    _rt_rm(runtime, req.container_name)

    rc, out, err = _rt_run(
        runtime, req.container_name, req.image, [(req.port, 5432)],
        {"POSTGRES_DB": req.db_name, "POSTGRES_USER": req.db_user, "POSTGRES_PASSWORD": req.db_password},
        [],
    )
    if rc != 0:
        return {"success": False, "error": err or out, "runtime": runtime}

    container_id = out.strip()

    # Wait for Postgres to be ready
    ready = _wait_for_postgres(req.port, req.db_name, req.db_user, req.db_password, timeout=30)

    dsn = f"postgresql://{req.db_user}:{req.db_password}@localhost:{req.port}/{req.db_name}"
    _pg_container = {
        "container_name": req.container_name,
        "container_id": container_id[:12],
        "image": req.image,
        "port": req.port,
        "db_name": req.db_name,
        "db_user": req.db_user,
        "db_password": req.db_password,
        "dsn": dsn,
        "runtime": runtime,
        "started_at": datetime.utcnow().isoformat(),
        "ready": ready,
    }
    return {
        "success": True,
        "ready": ready,
        "dsn": dsn,
        "container": _pg_container,
        "message": f"Container '{req.container_name}' started via {runtime}." + ("" if ready else " WARNING: Postgres not yet ready — retry in a few seconds."),
    }


@router.post("/postgres/stop")
def postgres_stop():
    _recover_tracked()
    global _pg_container
    if not _pg_container:
        return {"success": False, "error": "No container tracked. Start one first."}
    runtime = _pg_container.get("runtime", "docker")
    name = _pg_container.get("container_name", "lab-postgres")
    rc, out, err = _rt_rm(runtime, name)
    _pg_container = {}
    return {"success": rc == 0, "message": f"Container '{name}' stopped.", "error": err if rc != 0 else None}


@router.get("/postgres/status")
def postgres_status():
    _recover_tracked()
    if not _pg_container:
        return {"running": False, "container": None}
    runtime = _pg_container.get("runtime", "docker")
    name = _pg_container.get("container_name", "lab-postgres")
    running = _rt_running(runtime, name)
    return {"running": running, "container": {**_pg_container, "db_password": "***"}}


@router.post("/postgres/exec")
def postgres_exec(req: SqlExecRequest):
    _recover_tracked()
    port     = req.port     or _pg_container.get("port",        5433)
    db_name  = req.db_name  or _pg_container.get("db_name",   "labdb")
    db_user  = req.db_user  or _pg_container.get("db_user",   "labuser")
    db_password = req.db_password or _pg_container.get("db_password", "labpass")

    try:
        conn = _pg_connect(port, db_name, db_user, db_password)
        conn.autocommit = False
        cur = conn.cursor()

        # Split into individual statements
        stmts = [s.strip() for s in req.sql.split(";") if s.strip()]
        results = []
        for stmt in stmts:
            cur.execute(stmt)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                results.append({"statement": stmt[:100], "columns": cols, "rows": [list(r) for r in rows[:200]], "row_count": len(rows)})
            else:
                results.append({"statement": stmt[:100], "rowcount": cur.rowcount})
        conn.commit()
        conn.close()
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/postgres/seed")
def postgres_seed(req: SeedRequest):
    _recover_tracked()
    port     = req.port     or _pg_container.get("port",        5433)
    db_name  = req.db_name  or _pg_container.get("db_name",   "labdb")
    db_user  = req.db_user  or _pg_container.get("db_user",   "labuser")
    db_password = req.db_password or _pg_container.get("db_password", "labpass")

    if req.dataset == "custom":
        if not req.custom_ddl:
            return {"success": False, "error": "Provide 'custom_ddl' for the 'custom' dataset."}
        sql = req.custom_ddl
    elif req.dataset in _DATASETS:
        sql = _DATASETS[req.dataset]
    else:
        return {"success": False, "error": f"Unknown dataset '{req.dataset}'. Choose: {list(_DATASETS.keys())} or 'custom'."}

    try:
        conn = _pg_connect(port, db_name, db_user, db_password)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql)
        conn.close()
        return {"success": True, "dataset": req.dataset, "message": f"Dataset '{req.dataset}' seeded successfully into {db_name}."}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Generic service containers (MySQL, MongoDB, Elasticsearch, ...) ───────────
#
# Each catalog entry describes how to run a service in Docker/Podman:
#   env / command  — templates formatted with {user} {password} {database} {port}
#   ready          — {"type": "http", "url": ...} polled from the host, or
#                    {"type": "exec", "cmd": [...]} run inside the container
#   conn           — connection string template shown to the user

_SERVICES: Dict[str, Dict[str, Any]] = {
    "mysql": {
        "category": "relational", "label": "MySQL", "icon": "🐬",
        "image": "mysql:8.4", "container_port": 3306, "host_port": 3307,
        "fields": ["user", "password", "database"],
        "user": "labuser", "password": "labpass", "database": "labdb",
        "env": {
            "MYSQL_ROOT_PASSWORD": "{password}", "MYSQL_DATABASE": "{database}",
            "MYSQL_USER": "{user}", "MYSQL_PASSWORD": "{password}",
        },
        "ready": {"type": "exec", "cmd": ["mysqladmin", "ping", "-h127.0.0.1", "-uroot", "-p{password}", "--silent"]},
        "conn": "mysql://{user}:{password}@localhost:{port}/{database}",
        "timeout": 90,
    },
    "mongodb": {
        "category": "nosql", "label": "MongoDB", "icon": "🍃",
        "image": "mongo:7", "container_port": 27017, "host_port": 27018,
        "fields": ["user", "password", "database"],
        "user": "labuser", "password": "labpass", "database": "labdb",
        "env": {
            "MONGO_INITDB_ROOT_USERNAME": "{user}", "MONGO_INITDB_ROOT_PASSWORD": "{password}",
            "MONGO_INITDB_DATABASE": "{database}",
        },
        "ready": {"type": "exec", "cmd": ["mongosh", "--quiet", "--eval", "db.adminCommand('ping').ok"]},
        "conn": "mongodb://{user}:{password}@localhost:{port}/{database}?authSource=admin",
        "timeout": 60,
    },
    "elasticsearch": {
        "category": "search", "label": "Elasticsearch", "icon": "🔎",
        "image": "docker.elastic.co/elasticsearch/elasticsearch:8.13.4",
        "container_port": 9200, "host_port": 9201,
        "fields": [],
        "env": {
            "discovery.type": "single-node", "xpack.security.enabled": "false",
            "ES_JAVA_OPTS": "-Xms512m -Xmx512m",
        },
        "ready": {"type": "http", "url": "http://localhost:{port}/_cluster/health"},
        "conn": "http://localhost:{port}",
        "timeout": 120,
        "note": "Needs ~1 GB free memory (Podman machine / Docker Desktop). Security is disabled.",
    },
    "redis": {
        "category": "cache", "label": "Redis", "icon": "🧰",
        "image": "redis:7-alpine", "container_port": 6379, "host_port": 6380,
        "fields": ["password"], "password": "labpass",
        "env": {},
        "command": ["redis-server", "--requirepass", "{password}"],
        "ready": {"type": "exec", "cmd": ["redis-cli", "-a", "{password}", "ping"]},
        "conn": "redis://:{password}@localhost:{port}/0",
        "timeout": 30,
    },
    "qdrant": {
        "category": "vector", "label": "Qdrant", "icon": "🧭",
        "image": "qdrant/qdrant:v1.12.0", "container_port": 6333, "host_port": 6333,
        "fields": [],
        "env": {},
        "extra_ports": ["6334:6334"],
        "ready": {"type": "http", "url": "http://localhost:{port}/healthz"},
        "conn": "http://localhost:{port}",
        "timeout": 30,
        "note": "Vector DB. REST on the host port, gRPC on 6334.",
    },
    "neo4j": {
        "category": "nosql", "label": "Neo4j", "icon": "🕸️",
        "image": "neo4j:5", "container_port": 7474, "host_port": 7475,
        "fields": ["password"], "user": "neo4j", "password": "labpass123",
        "env": {"NEO4J_AUTH": "neo4j/{password}"},
        "extra_ports": ["7688:7687"],
        "ready": {"type": "http", "url": "http://localhost:{port}/"},
        "conn": "bolt://neo4j:{password}@localhost:7688  (browser: http://localhost:{port})",
        "timeout": 90,
        "note": "Host port is the HTTP browser; Bolt is on 7688. Password must be 8+ characters.",
    },
    "minio": {
        "category": "storage", "label": "MinIO", "icon": "🪣",
        "image": "minio/minio:latest", "container_port": 9000, "host_port": 9000,
        "fields": ["user", "password"], "user": "labuser", "password": "labpass123",
        "env": {"MINIO_ROOT_USER": "{user}", "MINIO_ROOT_PASSWORD": "{password}"},
        "command": ["server", "/data", "--console-address", ":9001"],
        "extra_ports": ["9001:9001"],
        "ready": {"type": "http", "url": "http://localhost:{port}/minio/health/live"},
        "conn": "s3 endpoint http://localhost:{port}  (console: http://localhost:9001)",
        "timeout": 30,
        "note": "S3-compatible object storage. Password must be 8+ characters.",
    },
    "mariadb": {
        "category": "relational", "label": "MariaDB", "icon": "🦭",
        "image": "mariadb:11", "container_port": 3306, "host_port": 3308,
        "fields": ["user", "password", "database"],
        "user": "labuser", "password": "labpass", "database": "labdb",
        "env": {
            "MARIADB_ROOT_PASSWORD": "{password}", "MARIADB_DATABASE": "{database}",
            "MARIADB_USER": "{user}", "MARIADB_PASSWORD": "{password}",
        },
        "ready": {"type": "exec", "cmd": ["mariadb-admin", "ping", "-h127.0.0.1", "-uroot", "-p{password}", "--silent"]},
        "conn": "mysql://{user}:{password}@localhost:{port}/{database}",
        "timeout": 90,
    },
    "clickhouse": {
        "category": "analytics", "label": "ClickHouse", "icon": "🟨",
        "image": "clickhouse/clickhouse-server:24.8", "container_port": 8123, "host_port": 8124,
        "fields": ["user", "password", "database"],
        "user": "labuser", "password": "labpass", "database": "labdb",
        "env": {
            "CLICKHOUSE_USER": "{user}", "CLICKHOUSE_PASSWORD": "{password}",
            "CLICKHOUSE_DB": "{database}", "CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT": "1",
        },
        "ready": {"type": "http", "url": "http://localhost:{port}/ping"},
        "conn": "clickhouse+http://{user}:{password}@localhost:{port}/{database}",
        "timeout": 60,
        "note": "Columnar OLAP database. Only the HTTP interface (8123) is exposed.",
    },
    "cassandra": {
        "category": "nosql", "label": "Cassandra", "icon": "👁️",
        "image": "cassandra:5", "container_port": 9042, "host_port": 9043,
        "fields": [],
        "env": {"MAX_HEAP_SIZE": "512M", "HEAP_NEWSIZE": "128M", "CASSANDRA_CLUSTER_NAME": "lab"},
        "ready": {"type": "exec", "cmd": ["cqlsh", "-e", "describe keyspaces"]},
        "conn": "cassandra://localhost:{port}  (CQL, no auth)",
        "timeout": 180,
        "note": "Wide-column store. Slow to boot (1–2 min) and needs ~1 GB free memory. Auth is disabled.",
    },
    "couchdb": {
        "category": "nosql", "label": "CouchDB", "icon": "🛋️",
        "image": "couchdb:3", "container_port": 5984, "host_port": 5985,
        "fields": ["user", "password"], "user": "labuser", "password": "labpass",
        "env": {"COUCHDB_USER": "{user}", "COUCHDB_PASSWORD": "{password}"},
        "ready": {"type": "http", "url": "http://localhost:{port}/_up"},
        "conn": "http://{user}:{password}@localhost:{port}  (Fauxton: /_utils)",
        "timeout": 60,
    },
    "opensearch": {
        "category": "search", "label": "OpenSearch", "icon": "🔍",
        "image": "opensearchproject/opensearch:2.17.1", "container_port": 9200, "host_port": 9202,
        "fields": [],
        "env": {
            "discovery.type": "single-node", "DISABLE_SECURITY_PLUGIN": "true",
            "DISABLE_INSTALL_DEMO_CONFIG": "true", "OPENSEARCH_JAVA_OPTS": "-Xms512m -Xmx512m",
        },
        "ready": {"type": "http", "url": "http://localhost:{port}/_cluster/health"},
        "conn": "http://localhost:{port}",
        "timeout": 120,
        "note": "Needs ~1 GB free memory. Security plugin is disabled.",
    },
    "chroma": {
        "category": "vector", "label": "Chroma", "icon": "🎨",
        "image": "chromadb/chroma:0.5.20", "container_port": 8000, "host_port": 8002,
        "fields": [],
        "env": {"ANONYMIZED_TELEMETRY": "false"},
        "ready": {"type": "http", "url": "http://localhost:{port}/api/v1/heartbeat"},
        "conn": "http://localhost:{port}",
        "timeout": 60,
        "note": "Vector DB. Use chromadb.HttpClient(host='localhost', port=<host port>).",
    },
    "weaviate": {
        "category": "vector", "label": "Weaviate", "icon": "🧬",
        "image": "cr.weaviate.io/semitechnologies/weaviate:1.27.0", "container_port": 8080, "host_port": 8081,
        "fields": [],
        "env": {
            "AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED": "true", "PERSISTENCE_DATA_PATH": "/var/lib/weaviate",
            "DEFAULT_VECTORIZER_MODULE": "none", "CLUSTER_HOSTNAME": "node1",
        },
        "extra_ports": ["50051:50051"],
        "ready": {"type": "http", "url": "http://localhost:{port}/v1/.well-known/ready"},
        "conn": "http://localhost:{port}  (gRPC: localhost:50051)",
        "timeout": 60,
        "note": "Vector DB with anonymous access and no vectorizer module (bring your own embeddings).",
    },

    # ── Messaging & streaming ──
    # Kafka-compatible brokers expose two listeners: an internal one (used by the
    # readiness check inside the container) and an external one advertised as
    # localhost:{port} so host clients can connect on any host port.
    "kafka": {
        "category": "messaging", "label": "Apache Kafka", "icon": "📨",
        "image": "apache/kafka:3.8.0", "container_port": 9092, "host_port": 9092,
        "fields": [],
        "env": {
            "KAFKA_NODE_ID": "1", "KAFKA_PROCESS_ROLES": "broker,controller",
            "KAFKA_LISTENERS": "EXTERNAL://:9092,INTERNAL://:19092,CONTROLLER://:9093",
            "KAFKA_ADVERTISED_LISTENERS": "EXTERNAL://localhost:{port},INTERNAL://localhost:19092",
            "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "CONTROLLER:PLAINTEXT,INTERNAL:PLAINTEXT,EXTERNAL:PLAINTEXT",
            "KAFKA_INTER_BROKER_LISTENER_NAME": "INTERNAL", "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
            "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
            "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1", "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": "1",
            "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": "1", "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS": "0",
            "KAFKA_NUM_PARTITIONS": "3", "KAFKA_AUTO_CREATE_TOPICS_ENABLE": "true",
        },
        "ready": {"type": "exec", "cmd": ["/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "localhost:19092", "--list"]},
        "conn": "bootstrap.servers=localhost:{port}",
        "timeout": 90,
        "note": "Single-node KRaft broker (no ZooKeeper). Topics are auto-created on first produce.",
    },
    "confluent": {
        "category": "messaging", "label": "Confluent Kafka", "icon": "🌊",
        "image": "confluentinc/cp-kafka:7.7.1", "container_port": 9092, "host_port": 9094,
        "fields": [],
        "env": {
            "CLUSTER_ID": "MkU3OEVBNTcwNTJENDM2Qk", "KAFKA_NODE_ID": "1",
            "KAFKA_PROCESS_ROLES": "broker,controller",
            "KAFKA_LISTENERS": "EXTERNAL://0.0.0.0:9092,INTERNAL://0.0.0.0:19092,CONTROLLER://0.0.0.0:9093",
            "KAFKA_ADVERTISED_LISTENERS": "EXTERNAL://localhost:{port},INTERNAL://localhost:19092",
            "KAFKA_LISTENER_SECURITY_PROTOCOL_MAP": "CONTROLLER:PLAINTEXT,INTERNAL:PLAINTEXT,EXTERNAL:PLAINTEXT",
            "KAFKA_INTER_BROKER_LISTENER_NAME": "INTERNAL", "KAFKA_CONTROLLER_LISTENER_NAMES": "CONTROLLER",
            "KAFKA_CONTROLLER_QUORUM_VOTERS": "1@localhost:9093",
            "KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR": "1", "KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR": "1",
            "KAFKA_TRANSACTION_STATE_LOG_MIN_ISR": "1", "KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS": "0",
            "KAFKA_HEAP_OPTS": "-Xms256m -Xmx512m",
        },
        "ready": {"type": "exec", "cmd": ["kafka-topics", "--bootstrap-server", "localhost:19092", "--list"]},
        "conn": "bootstrap.servers=localhost:{port}",
        "timeout": 120,
        "note": "Confluent Platform broker in KRaft mode. Schema Registry / Connect are not included.",
    },
    "redpanda": {
        "category": "messaging", "label": "Redpanda", "icon": "🐼",
        "image": "redpandadata/redpanda:v24.2.7", "container_port": 19092, "host_port": 19092,
        "fields": [],
        "env": {},
        "command": [
            "redpanda", "start", "--mode", "dev-container", "--smp", "1",
            "--kafka-addr", "internal://0.0.0.0:9092,external://0.0.0.0:19092",
            "--advertise-kafka-addr", "internal://localhost:9092,external://localhost:{port}",
        ],
        "ready": {"type": "exec", "cmd": ["rpk", "cluster", "health", "--exit-when-healthy"]},
        "conn": "bootstrap.servers=localhost:{port}",
        "timeout": 60,
        "note": "Kafka-API compatible, single binary, fast to boot. Use any Kafka client.",
    },
    "rabbitmq": {
        "category": "messaging", "label": "RabbitMQ", "icon": "🐇",
        "image": "rabbitmq:3.13-management", "container_port": 5672, "host_port": 5672,
        "fields": ["user", "password"], "user": "labuser", "password": "labpass",
        "env": {"RABBITMQ_DEFAULT_USER": "{user}", "RABBITMQ_DEFAULT_PASS": "{password}"},
        "extra_ports": ["15672:15672"],
        "ready": {"type": "exec", "cmd": ["rabbitmq-diagnostics", "-q", "check_port_connectivity"]},
        "conn": "amqp://{user}:{password}@localhost:{port}/  (UI: http://localhost:15672)",
        "timeout": 90,
        "note": "AMQP 0-9-1 broker with the management UI on 15672.",
    },
    "nats": {
        "category": "messaging", "label": "NATS", "icon": "⚡",
        "image": "nats:2.10-alpine", "container_port": 4222, "host_port": 4222,
        "fields": [],
        "env": {},
        "command": ["-js", "-m", "8222"],
        "extra_ports": ["8222:8222"],
        "ready": {"type": "http", "url": "http://localhost:8222/healthz"},
        "conn": "nats://localhost:{port}  (monitoring: http://localhost:8222)",
        "timeout": 30,
        "note": "Lightweight pub/sub with JetStream persistence enabled.",
    },
    "pulsar": {
        "category": "messaging", "label": "Apache Pulsar", "icon": "🌟",
        "image": "apachepulsar/pulsar:3.3.2", "container_port": 6650, "host_port": 6650,
        "fields": [],
        "env": {"PULSAR_MEM": "-Xms512m -Xmx512m -XX:MaxDirectMemorySize=256m"},
        "command": ["bin/pulsar", "standalone"],
        "extra_ports": ["8083:8080"],
        "ready": {"type": "http", "url": "http://localhost:8083/admin/v2/brokers/health"},
        "conn": "pulsar://localhost:{port}  (admin: http://localhost:8083)",
        "timeout": 180,
        "note": "Standalone mode. Slow to boot (1–2 min) and needs ~1 GB free memory.",
    },
    "artemis": {
        "category": "messaging", "label": "ActiveMQ Artemis", "icon": "🪶",
        "image": "apache/activemq-artemis:2.37.0", "container_port": 61616, "host_port": 61616,
        "fields": ["user", "password"], "user": "labuser", "password": "labpass",
        "env": {"ARTEMIS_USER": "{user}", "ARTEMIS_PASSWORD": "{password}", "ANONYMOUS_LOGIN": "false"},
        "extra_ports": ["8161:8161", "5673:5672"],
        "ready": {"type": "http", "url": "http://localhost:8161/"},
        "conn": "tcp://localhost:{port}  (AMQP: localhost:5673, console: http://localhost:8161)",
        "timeout": 60,
        "note": "JMS broker speaking Core, AMQP 1.0, STOMP and MQTT on the acceptor port.",
    },
    "mosquitto": {
        "category": "messaging", "label": "Mosquitto (MQTT)", "icon": "🦟",
        "image": "eclipse-mosquitto:2", "container_port": 1883, "host_port": 1883,
        "fields": [],
        "env": {},
        "command": ["mosquitto", "-c", "/mosquitto-no-auth.conf"],
        "ready": {"type": "exec", "cmd": ["mosquitto_pub", "-h", "localhost", "-t", "lab/ping", "-m", "ping"]},
        "conn": "mqtt://localhost:{port}",
        "timeout": 30,
        "note": "MQTT broker with anonymous access — handy for IoT / event-driven agents.",
    },

    # ── Cloud emulators ──
    "localstack": {
        "category": "cloud", "label": "LocalStack", "icon": "☁️",
        "image": "localstack/localstack:3.8", "container_port": 4566, "host_port": 4566,
        "fields": [],
        "env": {"SERVICES": "sqs,sns,s3,kinesis,dynamodb,lambda", "AWS_DEFAULT_REGION": "us-east-1"},
        "ready": {"type": "http", "url": "http://localhost:{port}/_localstack/health"},
        "conn": "AWS endpoint http://localhost:{port}  (region us-east-1, any key/secret)",
        "timeout": 90,
        "note": "Emulates AWS SQS, SNS, S3, Kinesis, DynamoDB and Lambda on one endpoint.",
    },
}

# Display order + labels for the service catalog sidebar.
_SERVICE_CATEGORIES: List[Dict[str, str]] = [
    {"id": "relational", "label": "Relational", "icon": "🗄️"},
    {"id": "nosql",      "label": "NoSQL & Graph", "icon": "🍃"},
    {"id": "vector",     "label": "Vector DBs", "icon": "🧭"},
    {"id": "search",     "label": "Search", "icon": "🔎"},
    {"id": "cache",      "label": "Cache / KV", "icon": "⚡"},
    {"id": "analytics",  "label": "Analytics", "icon": "📊"},
    {"id": "messaging",  "label": "Messaging & Streaming", "icon": "📨"},
    {"id": "storage",    "label": "Object Storage", "icon": "🪣"},
    {"id": "cloud",      "label": "Cloud Emulators", "icon": "☁️"},
]

_svc_containers: Dict[str, Dict[str, Any]] = {}   # container_name -> details
_svc_auth: Dict[str, Dict[str, str]] = {}         # container_name -> user/password/database (never returned)

# Sample datasets for services that can be seeded. Scripts are piped to the
# client inside the container (mysql / mongosh), so no extra Python deps needed.
_SEEDS: Dict[str, Dict[str, str]] = {
    "mysql": {
        "ecommerce": """
SET FOREIGN_KEY_CHECKS=0;
DROP TABLE IF EXISTS order_items, orders, products, customers;
SET FOREIGN_KEY_CHECKS=1;

CREATE TABLE customers (
  id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(120) NOT NULL,
  email VARCHAR(200) UNIQUE NOT NULL, city VARCHAR(80), country VARCHAR(60) DEFAULT 'US',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE products (
  id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(200) NOT NULL, category VARCHAR(80),
  price DECIMAL(10,2) NOT NULL, stock INT DEFAULT 0
);
CREATE TABLE orders (
  id INT AUTO_INCREMENT PRIMARY KEY, customer_id INT, status VARCHAR(30) DEFAULT 'pending',
  total DECIMAL(10,2), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (customer_id) REFERENCES customers(id)
);
CREATE TABLE order_items (
  id INT AUTO_INCREMENT PRIMARY KEY, order_id INT, product_id INT,
  quantity INT NOT NULL, unit_price DECIMAL(10,2) NOT NULL,
  FOREIGN KEY (order_id) REFERENCES orders(id), FOREIGN KEY (product_id) REFERENCES products(id)
);

INSERT INTO customers (name, email, city, country) VALUES
  ('Alice Johnson','alice@example.com','New York','US'), ('Bob Smith','bob@example.com','London','GB'),
  ('Carol White','carol@example.com','Toronto','CA'),   ('David Kim','david@example.com','Seoul','KR'),
  ('Emma Brown','emma@example.com','Berlin','DE');
INSERT INTO products (name, category, price, stock) VALUES
  ('Laptop Pro 15','Electronics',1299.99,45), ('Wireless Mouse','Electronics',29.99,200),
  ('USB-C Hub','Electronics',49.99,150),      ('Standing Desk','Furniture',399.99,20),
  ('Office Chair','Furniture',249.99,35),     ('Python Handbook','Books',39.99,80),
  ('AI Primer','Books',34.99,120);
INSERT INTO orders (customer_id, status, total, created_at) VALUES
  (1,'completed',1329.98,DATE_SUB(NOW(),INTERVAL 10 DAY)), (2,'completed',79.98,DATE_SUB(NOW(),INTERVAL 7 DAY)),
  (3,'shipped',399.99,DATE_SUB(NOW(),INTERVAL 3 DAY)),     (4,'pending',74.98,DATE_SUB(NOW(),INTERVAL 1 DAY)),
  (1,'completed',249.99,DATE_SUB(NOW(),INTERVAL 5 DAY));
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  (1,1,1,1299.99),(1,2,1,29.99),(2,2,1,29.99),(2,3,1,49.99),(3,4,1,399.99),(4,6,1,39.99),(4,7,1,34.99),(5,5,1,249.99);
""",
        "hr": """
SET FOREIGN_KEY_CHECKS=0;
DROP TABLE IF EXISTS performance_reviews, employees, departments;
SET FOREIGN_KEY_CHECKS=1;

CREATE TABLE departments (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL, budget DECIMAL(12,2));
CREATE TABLE employees (
  id INT AUTO_INCREMENT PRIMARY KEY, first_name VARCHAR(60) NOT NULL, last_name VARCHAR(60) NOT NULL,
  email VARCHAR(200) UNIQUE NOT NULL, department_id INT, title VARCHAR(100), salary DECIMAL(10,2),
  hired_at DATE, active BOOLEAN DEFAULT TRUE, FOREIGN KEY (department_id) REFERENCES departments(id)
);
CREATE TABLE performance_reviews (
  id INT AUTO_INCREMENT PRIMARY KEY, employee_id INT, reviewer VARCHAR(120),
  score INT, notes TEXT, reviewed_at DATE, FOREIGN KEY (employee_id) REFERENCES employees(id)
);

INSERT INTO departments (name, budget) VALUES
  ('Engineering',2500000), ('Data Science',1800000), ('Product',900000), ('Marketing',600000);
INSERT INTO employees (first_name, last_name, email, department_id, title, salary, hired_at) VALUES
  ('Alice','Park','alice.park@corp.com',1,'Senior Engineer',120000,'2021-03-15'),
  ('Ben','Clarke','ben.clarke@corp.com',1,'Staff Engineer',145000,'2019-07-01'),
  ('Carol','Nguyen','carol.n@corp.com',2,'ML Engineer',135000,'2022-01-10'),
  ('David','Santos','david.s@corp.com',2,'Data Scientist',118000,'2020-11-20'),
  ('Emma','Wilson','emma.w@corp.com',3,'Product Manager',115000,'2021-06-05'),
  ('Frank','Lee','frank.lee@corp.com',4,'Marketing Lead',95000,'2020-02-14');
INSERT INTO performance_reviews (employee_id, reviewer, score, notes, reviewed_at) VALUES
  (1,'Ben Clarke',5,'Exceptional delivery on Q3 platform migration.','2024-01-15'),
  (2,'VP Eng',4,'Strong technical leadership, good mentoring.','2024-01-15'),
  (3,'Carol Nguyen',5,'Built the entire recommendation model.','2024-01-16'),
  (4,'Carol Nguyen',3,'Good work but missed two sprint deadlines.','2024-01-16'),
  (5,'CEO',4,'Roadmap quality improved significantly.','2024-01-17');
""",
    },
    "mongodb": {
        "ecommerce": """
db.customers.drop(); db.products.drop(); db.orders.drop();
db.customers.insertMany([
  {_id: 1, name: 'Alice Johnson', email: 'alice@example.com', city: 'New York', country: 'US'},
  {_id: 2, name: 'Bob Smith',     email: 'bob@example.com',   city: 'London',   country: 'GB'},
  {_id: 3, name: 'Carol White',   email: 'carol@example.com', city: 'Toronto',  country: 'CA'},
  {_id: 4, name: 'David Kim',     email: 'david@example.com', city: 'Seoul',    country: 'KR'},
  {_id: 5, name: 'Emma Brown',    email: 'emma@example.com',  city: 'Berlin',   country: 'DE'}
]);
db.products.insertMany([
  {_id: 1, name: 'Laptop Pro 15',   category: 'Electronics', price: 1299.99, stock: 45},
  {_id: 2, name: 'Wireless Mouse',  category: 'Electronics', price: 29.99,   stock: 200},
  {_id: 3, name: 'USB-C Hub',       category: 'Electronics', price: 49.99,   stock: 150},
  {_id: 4, name: 'Standing Desk',   category: 'Furniture',   price: 399.99,  stock: 20},
  {_id: 5, name: 'Office Chair',    category: 'Furniture',   price: 249.99,  stock: 35},
  {_id: 6, name: 'Python Handbook', category: 'Books',       price: 39.99,   stock: 80},
  {_id: 7, name: 'AI Primer',       category: 'Books',       price: 34.99,   stock: 120}
]);
const day = 86400000;
db.orders.insertMany([
  {customer_id: 1, status: 'completed', total: 1329.98, created_at: new Date(Date.now() - 10*day), items: [{product_id: 1, quantity: 1, unit_price: 1299.99}, {product_id: 2, quantity: 1, unit_price: 29.99}]},
  {customer_id: 2, status: 'completed', total: 79.98,   created_at: new Date(Date.now() - 7*day),  items: [{product_id: 2, quantity: 1, unit_price: 29.99}, {product_id: 3, quantity: 1, unit_price: 49.99}]},
  {customer_id: 3, status: 'shipped',   total: 399.99,  created_at: new Date(Date.now() - 3*day),  items: [{product_id: 4, quantity: 1, unit_price: 399.99}]},
  {customer_id: 4, status: 'pending',   total: 74.98,   created_at: new Date(Date.now() - 1*day),  items: [{product_id: 6, quantity: 1, unit_price: 39.99}, {product_id: 7, quantity: 1, unit_price: 34.99}]},
  {customer_id: 1, status: 'completed', total: 249.99,  created_at: new Date(Date.now() - 5*day),  items: [{product_id: 5, quantity: 1, unit_price: 249.99}]}
]);
print('customers=' + db.customers.countDocuments() + ' products=' + db.products.countDocuments() + ' orders=' + db.orders.countDocuments());
""",
        "hr": """
db.departments.drop(); db.employees.drop();
db.departments.insertMany([
  {_id: 1, name: 'Engineering', budget: 2500000}, {_id: 2, name: 'Data Science', budget: 1800000},
  {_id: 3, name: 'Product', budget: 900000},      {_id: 4, name: 'Marketing', budget: 600000}
]);
db.employees.insertMany([
  {first_name: 'Alice', last_name: 'Park',   email: 'alice.park@corp.com', department_id: 1, title: 'Senior Engineer', salary: 120000, hired_at: new Date('2021-03-15'), reviews: [{reviewer: 'Ben Clarke', score: 5, notes: 'Exceptional delivery on Q3 platform migration.'}]},
  {first_name: 'Ben',   last_name: 'Clarke', email: 'ben.clarke@corp.com', department_id: 1, title: 'Staff Engineer',  salary: 145000, hired_at: new Date('2019-07-01'), reviews: [{reviewer: 'VP Eng', score: 4, notes: 'Strong technical leadership, good mentoring.'}]},
  {first_name: 'Carol', last_name: 'Nguyen', email: 'carol.n@corp.com',    department_id: 2, title: 'ML Engineer',     salary: 135000, hired_at: new Date('2022-01-10'), reviews: [{reviewer: 'Carol Nguyen', score: 5, notes: 'Built the entire recommendation model.'}]},
  {first_name: 'David', last_name: 'Santos', email: 'david.s@corp.com',    department_id: 2, title: 'Data Scientist',  salary: 118000, hired_at: new Date('2020-11-20'), reviews: [{reviewer: 'Carol Nguyen', score: 3, notes: 'Good work but missed two sprint deadlines.'}]},
  {first_name: 'Emma',  last_name: 'Wilson', email: 'emma.w@corp.com',     department_id: 3, title: 'Product Manager', salary: 115000, hired_at: new Date('2021-06-05'), reviews: [{reviewer: 'CEO', score: 4, notes: 'Roadmap quality improved significantly.'}]},
  {first_name: 'Frank', last_name: 'Lee',    email: 'frank.lee@corp.com',  department_id: 4, title: 'Marketing Lead',  salary: 95000,  hired_at: new Date('2020-02-14'), reviews: []}
]);
print('departments=' + db.departments.countDocuments() + ' employees=' + db.employees.countDocuments());
""",
    },
}
_SEEDS["mariadb"] = _SEEDS["mysql"]   # MySQL dialect scripts run unchanged on MariaDB


class ServiceStartRequest(BaseModel):
    service: str = Field(..., description="Key from the service catalog, e.g. mysql, mongodb")
    container_name: Optional[str] = None
    image: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None
    runtime: str = Field(default="auto", description="auto | docker | podman | kubernetes")


class ServiceStopRequest(BaseModel):
    container_name: str


class ServiceSeedRequest(BaseModel):
    container_name: str
    dataset: str = Field(default="ecommerce", description="Dataset key for the service, e.g. ecommerce | hr")


def _wait_for_service(runtime: str, name: str, spec: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    ready = spec["ready"]
    deadline = time.time() + spec.get("timeout", 60)
    while time.time() < deadline:
        if ready["type"] == "http":
            try:
                if httpx.get(ready["url"].format(**ctx), timeout=3.0).status_code == 200:
                    return True
            except Exception:
                pass
        else:
            cmd = [a.format(**ctx) for a in ready["cmd"]]
            if _run(_rt_exec_cmd(runtime, name, cmd), timeout=10)[0] == 0:
                return True
        time.sleep(2)
    return False


@router.get("/services/catalog")
def services_catalog():
    keys = ("category", "label", "icon", "image", "host_port", "fields", "user", "password", "database", "note", "conn")
    return {
        "categories": _SERVICE_CATEGORIES,
        "services": {
            k: {**{f: v[f] for f in keys if f in v}, "datasets": list(_SEEDS.get(k, {}))}
            for k, v in _SERVICES.items()
        },
    }


@router.post("/services/start")
def services_start(req: ServiceStartRequest):
    spec = _SERVICES.get(req.service)
    if not spec:
        return {"success": False, "error": f"Unknown service '{req.service}'. Choose: {list(_SERVICES.keys())}"}

    runtime, problem = _resolve_runtime(req.runtime)
    if problem:
        return {"success": False, "error": problem, "runtime": req.runtime}
    name = req.container_name or f"lab-{req.service}"
    image = req.image or spec["image"]
    ctx = {
        "user": req.user or spec.get("user", ""),
        "password": req.password or spec.get("password", ""),
        "database": req.database or spec.get("database", ""),
        "port": req.port or spec["host_port"],
    }

    _rt_rm(runtime, name)

    ports = [(ctx["port"], spec["container_port"])]
    for extra in spec.get("extra_ports", []):
        h, c = extra.split(":")
        ports.append((int(h), int(c)))
    env = {k: v.format(**ctx) for k, v in spec["env"].items()}
    args = [a.format(**ctx) for a in spec.get("command", [])]

    rc, out, err = _rt_run(runtime, name, image, ports, env, args, timeout=300)  # first run may pull a large image
    if rc != 0:
        return {"success": False, "error": err or out, "runtime": runtime}

    ready = _wait_for_service(runtime, name, spec, ctx)
    conn = spec["conn"].format(**ctx)
    _svc_containers[name] = {
        "container_name": name,
        "service": req.service,
        "container_id": out.strip()[:12],
        "image": image,
        "port": ctx["port"],
        "runtime": runtime,
        "started_at": datetime.utcnow().isoformat(),
        "ready": ready,
        "conn": conn.replace(ctx["password"], "***") if ctx["password"] else conn,
    }
    _svc_auth[name] = {k: str(ctx[k]) for k in ("user", "password", "database")}
    return {
        "success": True,
        "ready": ready,
        "conn": conn,
        "container": _svc_containers[name],
        "message": f"{spec['label']} container '{name}' started via {runtime}."
                   + ("" if ready else " WARNING: not ready yet — check logs and retry in a few seconds."),
    }


@router.post("/services/stop")
def services_stop(req: ServiceStopRequest):
    _recover_tracked()
    c = _svc_containers.get(req.container_name)
    if not c:
        return {"success": False, "error": f"No tracked container '{req.container_name}'."}
    rc, _, err = _rt_rm(c["runtime"], req.container_name)
    if rc == 0:
        _svc_containers.pop(req.container_name, None)
        _svc_auth.pop(req.container_name, None)
    return {"success": rc == 0, "message": f"Container '{req.container_name}' stopped.", "error": err if rc != 0 else None}


@router.post("/services/seed")
def services_seed(req: ServiceSeedRequest):
    _recover_tracked()
    c = _svc_containers.get(req.container_name)
    if not c:
        return {"success": False, "error": f"No tracked container '{req.container_name}'."}
    seeds = _SEEDS.get(c["service"])
    if not seeds:
        return {"success": False, "error": f"Seeding is not supported for '{c['service']}'."}
    script = seeds.get(req.dataset)
    if script is None:
        return {"success": False, "error": f"Unknown dataset '{req.dataset}'. Choose: {list(seeds)}"}

    auth = _svc_auth.get(req.container_name, {})
    user, pw, db = auth.get("user", ""), auth.get("password", ""), auth.get("database", "")
    runtime, name = c["runtime"], req.container_name
    if c["service"] in ("mysql", "mariadb"):
        client = "mariadb" if c["service"] == "mariadb" else "mysql"
        cmd = _rt_exec_cmd(runtime, name, [client, f"-u{user}", f"-p{pw}", db], interactive=True)
    else:  # mongodb
        uri = f"mongodb://{user}:{pw}@localhost:27017/{db}?authSource=admin"
        cmd = _rt_exec_cmd(runtime, name, ["mongosh", "--quiet", uri], interactive=True)

    rc, out, err = _run(cmd, timeout=60, input_text=script)
    # mysql prints a password-on-CLI warning to stderr even on success
    if rc != 0:
        return {"success": False, "error": err or out}
    return {"success": True, "message": f"Dataset '{req.dataset}' seeded into {c['service']} '{db}'." + (f" {out}" if out else "")}


@router.get("/services/status")
def services_status():
    _recover_tracked()
    items = []
    for name, c in list(_svc_containers.items()):
        items.append({**c, "running": _rt_running(c["runtime"], name)})
    return {"containers": items}


@router.get("/services/logs")
def services_logs(container_name: str, tail: int = 100):
    _recover_tracked()
    c = _svc_containers.get(container_name)
    if not c:
        return {"success": False, "error": f"No tracked container '{container_name}'."}
    rc, out, err = _rt_logs(c["runtime"], container_name, tail)
    # most services log to stderr; `docker logs` forwards it on stderr
    return {"success": rc == 0, "logs": "\n".join(x for x in (out, err) if x)}



# ── PDF endpoints ─────────────────────────────────────────────────────────────

def _build_pdf(req: PdfGenerateRequest, output_path: str) -> None:
    """Render a PDF using reportlab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(output_path, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    story = []

    if req.template == "report":
        # Formatted report with header, date, and styled body
        title_style = ParagraphStyle("LabTitle", parent=styles["Title"],
                                      fontSize=20, spaceAfter=6, textColor=colors.HexColor("#1e293b"))
        story.append(Paragraph(req.title, title_style))
        story.append(Paragraph(f"Author: {req.author} &nbsp;|&nbsp; Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
                                ParagraphStyle("Meta", parent=styles["Normal"], fontSize=9, textColor=colors.grey)))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0"), spaceAfter=12))
        for para in req.content.split("\n\n"):
            story.append(Paragraph(para.strip(), styles["Normal"]))
            story.append(Spacer(1, 8))

    elif req.template == "bio":
        # Bio / profile card style
        story.append(Paragraph(req.title, styles["Title"]))
        story.append(Spacer(1, 12))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#6366f1"), spaceAfter=12))
        for line in req.content.split("\n"):
            if line.startswith("# "):
                story.append(Paragraph(line[2:], styles["Heading1"]))
            elif line.startswith("## "):
                story.append(Paragraph(line[3:], styles["Heading2"]))
            elif line.strip():
                story.append(Paragraph(line.strip(), styles["Normal"]))
            story.append(Spacer(1, 4))

    elif req.template == "invoice":
        # Simple invoice layout
        story.append(Paragraph(req.title, styles["Title"]))
        story.append(Spacer(1, 6))
        story.append(Paragraph(f"Date: {datetime.utcnow().strftime('%Y-%m-%d')} &nbsp;|&nbsp; Issued by: {req.author}",
                                styles["Normal"]))
        story.append(Spacer(1, 12))
        # Try to parse content as tab/pipe-separated table
        rows = []
        for line in req.content.strip().split("\n"):
            cols = [c.strip() for c in line.replace("|", "\t").split("\t") if c.strip()]
            if cols:
                rows.append(cols)
        if rows:
            t = Table(rows, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND",  (0,0), (-1,0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR",   (0,0), (-1,0), colors.white),
                ("FONTSIZE",    (0,0), (-1,-1), 10),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
                ("GRID", (0,0), (-1,-1), 0.5, colors.HexColor("#e2e8f0")),
                ("LEFTPADDING",  (0,0), (-1,-1), 6),
                ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ]))
            story.append(t)
        else:
            story.append(Paragraph(req.content, styles["Normal"]))

    else:
        # plain
        story.append(Paragraph(req.title, styles["Title"]))
        story.append(Spacer(1, 12))
        for para in req.content.split("\n\n"):
            story.append(Paragraph(para.strip(), styles["Normal"]))
            story.append(Spacer(1, 8))

    doc.build(story)


@router.post("/pdf/generate")
def pdf_generate(req: PdfGenerateRequest):
    if req.output_path:
        out_path = os.path.abspath(req.output_path)
        os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    else:
        suffix = f"_{req.template}_{uuid.uuid4().hex[:8]}.pdf"
        out_path = os.path.join(tempfile.gettempdir(), f"lab{suffix}")

    try:
        _build_pdf(req, out_path)
        size = os.path.getsize(out_path)
        return {"success": True, "path": out_path, "size_bytes": size,
                "message": f"PDF generated: {out_path} ({size:,} bytes)"}
    except ImportError:
        return {"success": False, "error": "reportlab not installed. Run: pip install reportlab"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/pdf/batch")
def pdf_batch(req: PdfBatchRequest):
    out_dir = os.path.abspath(req.output_dir) if req.output_dir else tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for doc_req in req.documents:
        if not doc_req.output_path:
            slug = doc_req.title.lower().replace(" ", "_")[:30]
            doc_req = doc_req.model_copy(update={"output_path": os.path.join(out_dir, f"{slug}_{uuid.uuid4().hex[:6]}.pdf")})
        try:
            _build_pdf(doc_req, doc_req.output_path)
            size = os.path.getsize(doc_req.output_path)
            results.append({"title": doc_req.title, "path": doc_req.output_path, "size_bytes": size, "success": True})
        except Exception as e:
            results.append({"title": doc_req.title, "error": str(e), "success": False})
    ok = sum(1 for r in results if r["success"])
    return {"success": ok == len(results), "generated": ok, "total": len(results), "files": results}


# ── Overall lab status ────────────────────────────────────────────────────────

@router.get("/status")
def lab_status():
    _recover_tracked()
    problems = {rt: _runtime_problem(rt) for rt in _RUNTIMES}
    docker_ok = problems["docker"] is None
    podman_ok = problems["podman"] is None
    kubernetes_ok = problems["kubernetes"] is None
    pg_running = False
    if _pg_container:
        pg_running = _rt_running(_pg_container.get("runtime", "docker"), _pg_container.get("container_name", "lab-postgres"))

    try:
        import reportlab  # noqa: F401
        reportlab_ok = True
    except ImportError:
        reportlab_ok = False

    return {
        "docker_available": docker_ok,
        "podman_available": podman_ok,
        "kubernetes_available": kubernetes_ok,
        "runtime_problems": {rt: p for rt, p in problems.items() if p},
        "reportlab_available": reportlab_ok,
        "postgres_container": {**_pg_container, "db_password": "***"} if _pg_container else None,
        "postgres_running": pg_running,
    }


# ── Ollama model management ───────────────────────────────────────────────────

_OLLAMA_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")


class OllamaPullRequest(BaseModel):
    model: str = Field(..., description="Model name to pull, e.g. 'llama3.2' or 'ibm/granite4'")


@router.get("/ollama/list")
async def ollama_list():
    """Return all locally installed Ollama models."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{_OLLAMA_BASE}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [
                    {
                        "name": m["name"],
                        "size": m.get("size", 0),
                        "modified_at": m.get("modified_at", ""),
                        "family": m.get("details", {}).get("family", ""),
                        "parameter_size": m.get("details", {}).get("parameter_size", ""),
                        "quantization_level": m.get("details", {}).get("quantization_level", ""),
                    }
                    for m in data.get("models", [])
                ]
                return {"models": models, "ollama_available": True}
    except Exception as e:
        return {"models": [], "ollama_available": False, "error": str(e)}
    return {"models": [], "ollama_available": False}


@router.post("/ollama/pull")
async def ollama_pull(req: OllamaPullRequest):
    """
    Pull an Ollama model and stream progress as Server-Sent Events.
    Each SSE event is a JSON object with fields:
      { status, digest, total, completed, percent, done, error }
    """

    async def _stream() -> AsyncGenerator[str, None]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{_OLLAMA_BASE}/api/pull",
                    json={"name": req.model, "stream": True},
                ) as resp:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        yield f"data: {json.dumps({'error': f'Ollama returned HTTP {resp.status_code}: {body.decode()}', 'done': True})}\n\n"
                        return

                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        total = obj.get("total", 0)
                        completed = obj.get("completed", 0)
                        percent = round((completed / total) * 100, 1) if total else 0
                        event = {
                            "status": obj.get("status", ""),
                            "digest": obj.get("digest", ""),
                            "total": total,
                            "completed": completed,
                            "percent": percent,
                            "done": obj.get("status") == "success",
                        }
                        yield f"data: {json.dumps(event)}\n\n"

                        if event["done"]:
                            return

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.delete("/ollama/{model_name:path}")
async def ollama_delete(model_name: str):
    """Delete a locally installed Ollama model."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                "DELETE",
                f"{_OLLAMA_BASE}/api/delete",
                json={"name": model_name},
            )
            if resp.status_code in (200, 204):
                return {"success": True, "model": model_name}
            body = resp.text
            return {"success": False, "error": f"HTTP {resp.status_code}: {body}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── llama.cpp (llama-server) status ───────────────────────────────────────────
# llama-server loads one model at launch, so there is nothing to pull or delete here;
# the Lab tab only probes a running server and helps build the launch command.

_LLAMACPP_BASE = os.environ.get("LLAMACPP_API_BASE", "http://localhost:8080")


@router.get("/llamacpp/status")
async def llamacpp_status(base_url: Optional[str] = None):
    """Probe a llama-server: /health (ok | loading), /v1/models and /props."""
    base = (base_url or _LLAMACPP_BASE).strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    if not re.match(r"^https?://", base):
        return {"available": False, "base_url": base, "error": "Base URL must start with http:// or https://"}

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            health = await client.get(f"{base}/health")
            if health.status_code == 503:
                return {"available": True, "base_url": base, "status": "loading", "models": []}
            if health.status_code != 200:
                return {"available": False, "base_url": base, "error": f"/health returned HTTP {health.status_code}"}

            models: List[str] = []
            props: Dict[str, Any] = {}
            try:
                r = await client.get(f"{base}/v1/models")
                if r.status_code == 200:
                    models = [m["id"] for m in r.json().get("data", []) if "id" in m]
            except Exception:
                pass
            try:
                r = await client.get(f"{base}/props")
                if r.status_code == 200:
                    props = r.json()
            except Exception:
                pass

            gen = props.get("default_generation_settings", {}) or {}
            return {
                "available": True,
                "base_url": base,
                "status": "ok",
                "models": models,
                "model_path": props.get("model_path", ""),
                "n_ctx": gen.get("n_ctx") or props.get("n_ctx"),
                "total_slots": props.get("total_slots"),
                "build_info": props.get("build_info", ""),
            }
    except Exception as e:
        return {"available": False, "base_url": base, "error": str(e)}


# ── llama.cpp install & managed servers ───────────────────────────────────────
# Native servers are child processes of the backend (tracked in memory, stopped on exit);
# container servers are named lab-llamacpp-<port> and found via `ps`, so they survive restarts.

_LLAMACPP_IMAGE = "ghcr.io/ggml-org/llama.cpp:server"
_LLAMACPP_CACHE = os.path.expanduser("~/.cache/llama.cpp")
_LLAMACPP_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/home/linuxbrew/.linuxbrew/bin")
_HF_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.\-]*/[\w.\-]+(:[\w.\-]+)?$")

_llama_procs: Dict[int, Dict[str, Any]] = {}   # port -> {proc, repo, mode, logs, started_at}


def _llamacpp_binary() -> Optional[str]:
    """llama-server on PATH, or in a Homebrew prefix the backend's PATH may not include."""
    found = shutil.which("llama-server")
    if found:
        return found
    for d in _LLAMACPP_BIN_DIRS:
        cand = os.path.join(d, "llama-server")
        if os.access(cand, os.X_OK):
            return cand
    return None


def _llamacpp_container(port: int) -> str:
    return f"lab-llamacpp-{port}"


def _llamacpp_containers() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for rt in ("docker", "podman"):
        if shutil.which(rt) is None:
            continue
        rc, out, _ = _run([rt, "ps", "-a", "--no-trunc", "--filter", "name=lab-llamacpp-",
                           "--format", "{{.Names}}\t{{.State}}\t{{.Command}}"], timeout=10)
        if rc != 0:
            continue
        for line in out.splitlines():
            parts = line.split("\t")
            name = parts[0]
            if not name.startswith("lab-llamacpp-"):
                continue
            port_s = name.rsplit("-", 1)[-1]
            cmd = parts[2] if len(parts) > 2 else ""
            m = re.search(r"-hf\s+(\S+)", cmd)
            items.append({
                "port": int(port_s) if port_s.isdigit() else None,
                "runtime": rt,
                "name": name,
                "repo": m.group(1).strip('"') if m else "",
                "mode": "embeddings" if "--embeddings" in cmd else "chat",
                "running": (len(parts) > 1 and parts[1].lower().startswith("running")),
            })
    return items


def _llamacpp_servers() -> List[Dict[str, Any]]:
    items = []
    for port, p in list(_llama_procs.items()):
        items.append({"port": port, "runtime": "native", "name": f"llama-server:{port}", "repo": p["repo"],
                      "mode": p["mode"], "running": p["proc"].poll() is None,
                      "exit_code": p["proc"].poll(), "started_at": p["started_at"]})
    return items + _llamacpp_containers()


def _stop_llama_procs() -> None:
    for p in _llama_procs.values():
        if p["proc"].poll() is None:
            p["proc"].terminate()


import atexit  # noqa: E402
atexit.register(_stop_llama_procs)


@router.get("/llamacpp/setup")
def llamacpp_setup():
    binary = _llamacpp_binary()
    version = ""
    if binary:
        rc, out, err = _run([binary, "--version"], timeout=10)
        lines = [l for l in (out + "\n" + err).splitlines() if l.strip().startswith("version")]
        version = lines[0].strip() if lines else ""
    system = platform.system().lower()   # darwin | linux | windows
    return {
        "platform": system,
        "binary": binary,
        "version": version,
        "installers": {
            "brew": shutil.which("brew") is not None and system in ("darwin", "linux"),
            "winget": shutil.which("winget") is not None and system == "windows",
        },
        "runtimes": {rt: _runtime_problem(rt) for rt in ("docker", "podman")},
        "image": _LLAMACPP_IMAGE,
        "servers": _llamacpp_servers(),
    }


class LlamaCppInstallRequest(BaseModel):
    method: str = Field(..., description="brew | winget | docker | podman")


@router.post("/llamacpp/install")
async def llamacpp_install(req: LlamaCppInstallRequest):
    """Run the installer and stream its output as SSE (see _stream_cmd)."""
    cmds = {
        "brew": ["brew", "install", "llama.cpp"],
        "winget": ["winget", "install", "--id", "ggml.llamacpp", "-e",
                   "--accept-source-agreements", "--accept-package-agreements"],
        "docker": ["docker", "pull", _LLAMACPP_IMAGE],
        "podman": ["podman", "pull", _LLAMACPP_IMAGE],
    }
    cmd = cmds.get(req.method)

    if not cmd:
        error = f"Unknown method {req.method!r}"
    elif req.method in ("docker", "podman"):
        error = _runtime_problem(req.method)
    else:
        error = None if shutil.which(cmd[0]) else f"{cmd[0]} is not on the backend PATH."
    return StreamingResponse(_stream_cmd(cmd or [], error), media_type="text/event-stream")


async def _stream_cmd(cmd: List[str], error: Optional[str] = None) -> AsyncGenerator[str, None]:
    """Run an installer and stream its output as SSE: {line} ... then {done, success, error?}."""
    if error:
        yield f"data: {json.dumps({'done': True, 'success': False, 'error': error})}\n\n"
        return
    yield f"data: {json.dumps({'line': '$ ' + ' '.join(cmd)})}\n\n"
    try:
        env = {**os.environ, "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_ENV_HINTS": "1"}
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env)
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            if line:
                yield f"data: {json.dumps({'line': line})}\n\n"
        rc = await proc.wait()
        ok = rc == 0
        yield f"data: {json.dumps({'done': True, 'success': ok, **({} if ok else {'error': f'Exited with code {rc}'})})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'done': True, 'success': False, 'error': str(e)})}\n\n"


class LlamaCppStartRequest(BaseModel):
    repo: str = Field(..., description="Hugging Face GGUF repo, e.g. ggml-org/gemma-3-1b-it-GGUF[:Q4_K_M]")
    mode: str = Field(default="chat", description="chat | embeddings")
    port: int = Field(default=8080, ge=1024, le=65535)
    ctx: int = Field(default=8192, ge=512, le=1_048_576)
    runtime: str = Field(default="native", description="native | docker | podman")


@router.post("/llamacpp/start")
def llamacpp_start(req: LlamaCppStartRequest):
    repo = req.repo.strip()
    if not _HF_REPO_RE.match(repo):
        return {"success": False, "error": "Repo must look like 'user/model-GGUF' (optionally ':QUANT')."}
    if req.mode not in ("chat", "embeddings"):
        return {"success": False, "error": "Mode must be 'chat' or 'embeddings'."}
    if any(s["port"] == req.port and s["running"] for s in _llamacpp_servers()):
        return {"success": False, "error": f"A llama-server is already running on port {req.port}. Stop it first."}

    args = ["-hf", repo, "--port", str(req.port)]
    args += ["--embeddings"] if req.mode == "embeddings" else ["-c", str(req.ctx)]

    if req.runtime == "native":
        binary = _llamacpp_binary()
        if not binary:
            return {"success": False, "error": "llama-server is not installed. Install it first."}
        old = _llama_procs.pop(req.port, None)
        if old and old["proc"].poll() is None:
            old["proc"].terminate()
        proc = subprocess.Popen([binary, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True, errors="replace", bufsize=1)
        logs: deque = deque(maxlen=400)

        def _pump() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                logs.append(line.rstrip())

        threading.Thread(target=_pump, daemon=True).start()
        _llama_procs[req.port] = {"proc": proc, "repo": repo, "mode": req.mode, "logs": logs,
                                  "started_at": datetime.utcnow().isoformat()}
        return {"success": True, "runtime": "native", "port": req.port,
                "message": f"llama-server starting on port {req.port}. The model downloads on first start."}

    if req.runtime not in ("docker", "podman"):
        return {"success": False, "error": "Runtime must be native, docker or podman."}
    problem = _runtime_problem(req.runtime)
    if problem:
        return {"success": False, "error": problem}
    name = _llamacpp_container(req.port)
    _rt_rm(req.runtime, name)
    os.makedirs(_LLAMACPP_CACHE, exist_ok=True)
    cmd = [req.runtime, "run", "-d", "--name", name, "-p", f"{req.port}:{req.port}",
           "-v", f"{_LLAMACPP_CACHE}:/root/.cache/llama.cpp", _LLAMACPP_IMAGE, *args, "--host", "0.0.0.0"]
    rc, out, err = _run(cmd, timeout=600)   # pulls the image first if it isn't present
    if rc != 0:
        return {"success": False, "error": err or out, "runtime": req.runtime}
    return {"success": True, "runtime": req.runtime, "port": req.port, "container_name": name,
            "message": f"Container '{name}' starting via {req.runtime}. The model downloads on first start."}


class LlamaCppStopRequest(BaseModel):
    port: int


@router.post("/llamacpp/stop")
def llamacpp_stop(req: LlamaCppStopRequest):
    p = _llama_procs.pop(req.port, None)
    if p:
        if p["proc"].poll() is None:
            p["proc"].terminate()
            try:
                p["proc"].wait(timeout=10)
            except subprocess.TimeoutExpired:
                p["proc"].kill()
        return {"success": True, "message": f"llama-server on port {req.port} stopped."}
    for c in _llamacpp_containers():
        if c["port"] == req.port:
            rc, _, err = _rt_rm(c["runtime"], c["name"])
            return {"success": rc == 0, "message": f"Container '{c['name']}' removed.", "error": err if rc else None}
    return {"success": False, "error": f"No managed llama-server on port {req.port}."}


@router.get("/llamacpp/logs")
def llamacpp_logs(port: int, tail: int = 150):
    tail = max(1, min(tail, 400))
    p = _llama_procs.get(port)
    if p:
        return {"success": True, "logs": "\n".join(list(p["logs"])[-tail:])}
    for c in _llamacpp_containers():
        if c["port"] == port:
            rc, out, err = _rt_logs(c["runtime"], c["name"], tail)
            return {"success": rc == 0, "logs": "\n".join(x for x in (out, err) if x)}
    return {"success": False, "error": f"No managed llama-server on port {port}."}
