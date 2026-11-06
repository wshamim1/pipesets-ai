"""Thin client over the Pipesets AI REST API."""

import json
import os
from typing import Any, Dict, Iterator, List, Optional

import httpx

DEFAULT_URL = "http://localhost:8000"
EXPORT_FORMATS = ["native_json", "openapi", "langchain", "crewai", "autogen", "docker_compose", "notebook"]


class PipesetsError(Exception):
    """Raised when the backend returns an error status."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class PipesetsClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
        user_id: Optional[str] = None,
        timeout: float = 130.0,
        api_key: Optional[str] = None,
        session_token: Optional[str] = None,
    ):
        self.base_url = (base_url or os.getenv("PIPESETS_URL") or DEFAULT_URL).rstrip("/")
        headers = {}
        # API key for the public /v1 routes; the key alone fixes tenant/project/user there.
        api_key = api_key or os.getenv("PIPESETS_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # Login session for the internal /api routes (from `pipesets login` or login());
        # sent separately so it can coexist with an API key
        session_token = session_token or os.getenv("PIPESETS_SESSION_TOKEN")
        if session_token:
            headers["X-Session-Token"] = session_token
        for header, value, env in (
            ("x-tenant-id", tenant_id, "PIPESETS_TENANT_ID"),
            ("x-project-id", project_id, "PIPESETS_PROJECT_ID"),
            ("x-user-id", user_id, "PIPESETS_USER_ID"),
        ):
            value = value or os.getenv(env)
            if value:
                headers[header] = value
        self._http = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PipesetsClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise PipesetsError(f"{resp.status_code}: {detail}", resp.status_code)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            raise PipesetsError(f"Cannot reach backend at {self.base_url}: {exc}") from exc
        self._raise_for_status(resp)
        return resp

    # ── health ───────────────────────────────────────────────────────────────

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/health").json()

    # ── auth ─────────────────────────────────────────────────────────────────

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """Sign in; later calls on this client use the new session. Returns token + memberships."""
        data = self._request("POST", "/api/auth/login", json={"email": email, "password": password}).json()
        self._http.headers["X-Session-Token"] = data["token"]
        return data

    def logout(self) -> None:
        self._request("POST", "/api/auth/logout")
        self._http.headers.pop("X-Session-Token", None)

    def me(self) -> Dict[str, Any]:
        return self._request("GET", "/api/auth/me").json()

    # ── apps (workflows) ─────────────────────────────────────────────────────

    def list_apps(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/apps").json()

    def get_app(self, app_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/apps/{app_id}").json()

    def create_app(self, name: str, description: str = "", flow_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = {"name": name, "description": description, "flow_data": flow_data or {}}
        return self._request("POST", "/api/apps", json=body).json()

    def update_app(self, app_id: str, **fields: Any) -> Dict[str, Any]:
        """Update name, description and/or flow_data."""
        return self._request("PUT", f"/api/apps/{app_id}", json=fields).json()

    def publish_app(self, app_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/api/apps/{app_id}/publish").json()

    def delete_app(self, app_id: str) -> None:
        self._request("DELETE", f"/api/apps/{app_id}")

    # ── pipelines (published apps) ───────────────────────────────────────────

    def list_pipelines(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/pipelines").json()

    def run_pipeline(
        self,
        app_id: str,
        prompt: str,
        timeout_ms: int = 120000,
        provider_keys: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run a published pipeline. Returns {ok, output, error, latency_ms, ...}."""
        body = {"prompt": prompt, "timeout_ms": timeout_ms, "provider_keys": provider_keys or {}}
        return self._request("POST", f"/api/pipelines/{app_id}/run", json=body).json()

    # ── streaming prompt run ─────────────────────────────────────────────────

    def stream(self, prompt: str, **fields: Any) -> Iterator[Dict[str, Any]]:
        """POST /api/run/stream and yield each SSE event as a dict.

        Extra keyword args are passed through as PromptRunRequest fields
        (config, app_id, session_id, attached_tools, ...).
        """
        yield from self._iter_sse("/api/run/stream", {"prompt": prompt, **fields})

    def _iter_sse(self, path: str, body: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        try:
            with self._http.stream("POST", path, json=body) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        yield json.loads(line[5:].strip())
        except httpx.ConnectError as exc:
            raise PipesetsError(f"Cannot reach backend at {self.base_url}: {exc}") from exc

    # ── export ───────────────────────────────────────────────────────────────

    def export_app(self, app_id: str, format: str = "native_json") -> str:
        return self._request("GET", f"/api/export/{app_id}", params={"format": format}).text

    # ── traces ───────────────────────────────────────────────────────────────

    def list_traces(self, limit: int = 20, app_id: Optional[str] = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": limit}
        if app_id:
            params["app_id"] = app_id
        return self._request("GET", "/api/traces", params=params).json()

    def get_run_traces(self, run_id: str) -> List[Dict[str, Any]]:
        return self._request("GET", f"/api/traces/{run_id}").json()

    # ── retrieval ────────────────────────────────────────────────────────────

    def list_collections(self) -> Any:
        return self._request("GET", "/api/retrieval/collections").json()

    # ── public /v1 API (requires api_key) ────────────────────────────────────

    def v1_list_apps(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/v1/apps").json()["data"]

    def v1_get_app(self, app_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/apps/{app_id}").json()

    def v1_run(
        self,
        app_id: str,
        prompt: str,
        session_id: Optional[str] = None,
        timeout_ms: int = 120000,
        provider_keys: Optional[Dict[str, str]] = None,
        user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a published app and wait. Returns {ok, output, error, meta, latency_ms, ...}.
        ``user`` names your end user, for apps with long-term memory."""
        body = self._v1_run_body(prompt, session_id, timeout_ms, provider_keys, stream=False, user=user)
        return self._request("POST", f"/v1/apps/{app_id}/run", json=body).json()

    def v1_stream(
        self,
        app_id: str,
        prompt: str,
        session_id: Optional[str] = None,
        timeout_ms: int = 120000,
        provider_keys: Optional[Dict[str, str]] = None,
        user: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Run a published app and yield its SSE events (same shapes as stream())."""
        body = self._v1_run_body(prompt, session_id, timeout_ms, provider_keys, stream=True, user=user)
        yield from self._iter_sse(f"/v1/apps/{app_id}/run", body)

    def v1_resume(
        self,
        run_id: str,
        action: Optional[str] = None,
        edited_output: Optional[str] = None,
        comment: Optional[str] = None,
        timeout_ms: int = 120000,
        provider_keys: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Continue a run that was interrupted or failed (no action), or a Master Agent run that
        paused at a human gate (action = approve, reject or edit). Returns the same shape as v1_run."""
        body: Dict[str, Any] = {"timeout_ms": timeout_ms, "provider_keys": provider_keys or {}}
        if action:
            body["gate_decision"] = {"action": action, "edited_output": edited_output, "comment": comment}
        return self._request("POST", f"/v1/runs/{run_id}/resume", json=body).json()

    # ── custom tools as code (/v1/tools; tools:* scopes) ─────────────────────

    def tools_list(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/v1/tools").json()["data"]

    def tool_get(self, name: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/tools/{name}").json()

    def tool_deploy(self, name: str, bundle: Dict[str, Any]) -> Dict[str, Any]:
        """Create the tool, or a new version when its content changed (``changed: False`` otherwise)."""
        return self._request("PUT", f"/v1/tools/{name}", json=bundle).json()

    def tool_versions(self, name: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/tools/{name}/versions").json()

    def tool_rollback(self, name: str, version: int) -> Dict[str, Any]:
        return self._request("POST", f"/v1/tools/{name}/rollback", json={"version": version}).json()

    def tool_run(self, name: str, args: Optional[Dict[str, Any]] = None, config: Optional[Dict[str, Any]] = None,
                 version: Optional[int] = None, input_text: str = "") -> Dict[str, Any]:
        """Run the deployed tool in the server's sandbox: {ok, output, error, version, duration_ms}."""
        body: Dict[str, Any] = {"args": args, "input": input_text, "config": config or {}}
        if version:
            body["version"] = version
        return self._request("POST", f"/v1/tools/{name}/run", json=body).json()

    @staticmethod
    def _v1_run_body(prompt, session_id, timeout_ms, provider_keys, stream: bool, user=None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"prompt": prompt, "stream": stream, "timeout_ms": timeout_ms,
                                "provider_keys": provider_keys or {}}
        if session_id:
            body["session_id"] = session_id
        if user:
            body["user"] = user
        return body
