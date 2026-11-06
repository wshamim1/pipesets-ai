"""Helpers shared by the test modules (fixtures live in conftest.py)."""


def hdr(user: str = "user_admin", project: str = "proj_research", tenant: str = "tenant_demo") -> dict:
    """Identity headers for AUTH_MODE=headers (the seeded demo tenant)."""
    return {"x-user-id": user, "x-tenant-id": tenant, "x-project-id": project}


def mock_flow(tag: str = "m", label: str = "") -> dict:
    """A one-node pipeline on the mock model provider."""
    return {"nodes": [{"id": tag, "type": "llm", "data": {"label": label or tag, "provider": "mock",
                                                          "model": "mock-gpt-4"}}], "edges": []}


def run_jobs() -> None:
    """Work every due job (scheduled / webhook runs, notifications) until none is left."""
    import asyncio

    from services import jobs
    jobs.load_handlers()
    asyncio.run(jobs.Worker().drain())


def run_row(table: str, run_row_id: str) -> dict:
    from db import get_db_connection
    conn = get_db_connection()
    try:
        return dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (run_row_id,)).fetchone())
    finally:
        conn.close()


def serve(app):
    """Serve an ASGI app on a free local port in a background thread; yields its base URL."""
    import socket
    import threading
    import time

    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
