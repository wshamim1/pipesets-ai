"""
Sandboxed Python execution for the python_interpreter tool and custom tools.

Backends (cfg["backend"]):
  container — podman/docker: no network (by default), read-only rootfs, dropped
              capabilities, memory/CPU/pid limits, non-root user. Real isolation.
  local     — hardened subprocess: scrubbed env, throwaway cwd, rlimits.
              NOT isolation: the code can still read any file the backend user can.
              The memory cap (RLIMIT_AS) is enforced on Linux only; macOS ignores it.
  remote    — the sandbox runner service (sandbox_runner.py) at SANDBOX_URL, which runs the
              code with its own podman as "container" above. For deployments: the backend
              gets no container engine and the runner holds no secrets. Authenticated with
              SANDBOX_TOKEN.
  auto      — remote if SANDBOX_URL is set, else container if a runtime is reachable,
              otherwise local. With SANDBOX_URL set, "container" means remote too.

Set SANDBOX_REQUIRE_ISOLATION=1 to make "auto" fail instead of falling back to local.

cfg["requirements"] (pip specs, e.g. ["requests>=2", "boto3"]) are installed into an environment
of their own, never the backend's: a cached image built FROM the base image (container) or a
cached venv under <data dir>/tool-envs/ (local). Either way the tool sees the standard library
plus exactly its requirements. Both are keyed by a hash of the specs, built once on first use
and reused (the first run waits for the install, up to INSTALL_TIMEOUT_S). Specs are plain package names
with optional extras / versions — URLs, paths and pip options are refused.

In the frozen desktop build sys.executable is the backend binary, which has no
``python -c``; the local backend runs it as ``--sandbox-exec`` instead (see desktop_main.py).
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from packaging.requirements import InvalidRequirement, Requirement

from paths import data_path
from services.child_env import scrubbed_env

logger = logging.getLogger("pipesets-ai-backend")

DEFAULT_IMAGE = "python:3.12-slim"
MAX_OUTPUT_CHARS = 20_000
MAX_REQUIREMENTS = 30
INSTALL_TIMEOUT_S = 600
_MB = 1024 * 1024

_runtime_cache: Dict[str, Any] = {"checked_at": None, "runtime": None}
_known_images: set = set()
_env_locks: Dict[str, threading.Lock] = {}
_env_locks_guard = threading.Lock()

# Runs inside the local subprocess: apply rlimits, then exec the user's code from stdin.
_LOCAL_BOOTSTRAP = """
import resource, sys
cpu, mem_mb = int(sys.argv[1]), int(sys.argv[2])
for name, val in (("RLIMIT_CPU", cpu), ("RLIMIT_FSIZE", 10 * 1024 * 1024),
                  ("RLIMIT_AS", mem_mb * 1024 * 1024)):
    try:
        resource.setrlimit(getattr(resource, name), (val, val))
    except (ValueError, OSError):
        pass
exec(compile(sys.stdin.read(), "<sandbox>", "exec"), {"__name__": "__main__"})
"""


# Runs a custom tool and writes {"result"} or {"error"} as JSON to stdout; the tool's own prints
# go to stderr. %r is the JSON request, as a str literal. A legacy tool is called as
# run(input_text, config); a typed one (services/tool_signature.py) as entrypoint(**args[, config=]).
# `from pipesets import tool` works without the SDK installed: a stand-in module provides a
# decorator that returns the function unchanged.
_TOOL_HARNESS = """
import json, sys, types
def _main(req):
    out, sys.stdout = sys.stdout, sys.stderr
    try:
        shim = types.ModuleType("pipesets")
        def tool(*a, **kw):
            if len(a) == 1 and callable(a[0]) and not kw:
                return a[0]
            return lambda fn: fn
        shim.tool = tool
        sys.modules.setdefault("pipesets", shim)
        ns = {"__name__": "custom_tool"}
        try:
            exec(compile(req["code"], "<custom_tool>", "exec"), ns)
        except SyntaxError as e:
            return {"error": f"Syntax error in tool code: {e}"}
        except Exception as e:
            return {"error": f"Error loading tool code: {e}"}
        name = req.get("entrypoint") or "run"
        fn = ns.get(name)
        if not callable(fn):
            return {"error": f"Tool code must define a function named '{name}'."}
        try:
            if req.get("args") is None:
                result = fn(req["input_text"], req["config"])
            else:
                kwargs = dict(req["args"])
                if req.get("takes_config"):
                    kwargs["config"] = req["config"]
                result = fn(**kwargs)
        except Exception as e:
            return {"error": f"Tool execution error: {type(e).__name__}: {e}"}
        if not isinstance(result, str):
            try:
                result = json.dumps(result, default=str, ensure_ascii=False)
            except (TypeError, ValueError):
                result = str(result)
        return {"result": result}
    finally:
        sys.stdout = out
sys.stdout.write(json.dumps(_main(json.loads(%r))))
"""


def isolation_required() -> bool:
    return os.environ.get("SANDBOX_REQUIRE_ISOLATION", "").lower() in ("1", "true", "yes")


def remote_url() -> str:
    return (os.environ.get("SANDBOX_URL") or "").strip().rstrip("/")


class SandboxError(Exception):
    """The code could not be run at all: no engine, image pull failure, timeout."""


def normalize_requirements(specs: Any) -> List[str]:
    """Validated, de-duplicated, sorted pip specs. Raises ValueError naming the bad one."""
    if isinstance(specs, str):
        specs = specs.replace(",", "\n").split()
    out = set()
    for raw in specs or []:
        spec = str(raw).strip()
        if not spec:
            continue
        if spec.startswith("-"):
            raise ValueError(f"'{spec}': pip options aren't allowed, only package names")
        try:
            req = Requirement(spec)
        except InvalidRequirement:
            raise ValueError(f"'{spec}' isn't a valid requirement (e.g. requests or requests>=2.31)") from None
        if req.url:
            raise ValueError(f"'{spec}': URLs and paths aren't allowed, only packages from the index")
        out.add(str(req))
    if len(out) > MAX_REQUIREMENTS:
        raise ValueError(f"At most {MAX_REQUIREMENTS} requirements per tool")
    return sorted(out)


def _env_key(base: str, requirements: List[str]) -> str:
    return hashlib.sha256(json.dumps([base, requirements]).encode()).hexdigest()[:16]


def _env_lock(key: str) -> threading.Lock:
    with _env_locks_guard:
        return _env_locks.setdefault(key, threading.Lock())


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n...(output truncated)"


def _format(returncode: int, stdout: str, stderr: str) -> str:
    if returncode == 0:
        return _truncate(stdout) or "(Script finished with no output)"
    return "Python Error:\n" + _truncate(stderr or stdout)


def _container_runtime() -> Optional[str]:
    """Return 'podman' or 'docker' if its engine is reachable (cached for 30s)."""
    checked_at = _runtime_cache["checked_at"]
    if checked_at is not None and time.monotonic() - checked_at < 30:
        return _runtime_cache["runtime"]
    found = None
    for rt in ("podman", "docker"):
        if not shutil.which(rt):
            continue
        try:
            if subprocess.run([rt, "info"], capture_output=True, timeout=5).returncode == 0:
                found = rt
                break
        except (subprocess.TimeoutExpired, OSError):
            continue
    _runtime_cache.update(checked_at=time.monotonic(), runtime=found)
    return found


def _ensure_image(rt: str, image: str) -> Optional[str]:
    """Pull the image once so the execution timeout doesn't include the download."""
    if image in _known_images:
        return None
    if subprocess.run([rt, "image", "inspect", image], capture_output=True).returncode != 0:
        logger.info(f"Sandbox: pulling image {image}")
        try:
            pull = subprocess.run([rt, "pull", image], capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return f"Python Sandbox: pulling image '{image}' timed out"
        if pull.returncode != 0:
            return f"Python Sandbox: could not pull image '{image}': {pull.stderr.strip()}"
    _known_images.add(image)
    return None


def _tool_image(rt: str, base: str, requirements: List[str]) -> str:
    """An image with the requirements installed on top of ``base``, built once and cached."""
    tag = f"pipesets-tool:{_env_key(base, requirements)}"
    with _env_lock(tag):
        if tag in _known_images:
            return tag
        if subprocess.run([rt, "image", "inspect", tag], capture_output=True).returncode != 0:
            err = _ensure_image(rt, base)
            if err:
                raise SandboxError(err)
            logger.info(f"Sandbox: building {tag} with {' '.join(requirements)}")
            # Exec form: the specs are arguments, never parsed by a shell
            pip = ["pip", "install", "--no-cache-dir", "--disable-pip-version-check", *requirements]
            dockerfile = f"FROM {base}\nRUN {json.dumps(pip)}\n"
            try:
                build = subprocess.run([rt, "build", "-t", tag, "-"], input=dockerfile, capture_output=True,
                                       text=True, timeout=INSTALL_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                raise SandboxError(f"Python Sandbox: installing {' '.join(requirements)} timed out") from None
            if build.returncode != 0:
                raise SandboxError("Python Sandbox: couldn't install the tool's requirements:\n"
                                   + _truncate((build.stderr or build.stdout).strip()[-4000:]))
        _known_images.add(tag)
    return tag


def _run_container(rt: str, code: str, timeout: int, memory_mb: int, image: str,
                   allow_network: bool, requirements: Optional[List[str]] = None) -> Tuple[int, str, str]:
    if requirements:
        image = _tool_image(rt, image, requirements)
    else:
        err = _ensure_image(rt, image)
        if err:
            raise SandboxError(err)
    name = f"sbx-{uuid.uuid4().hex[:12]}"
    cmd = [
        rt, "run", "--rm", "-i", "--name", name,
        "--memory", f"{memory_mb}m", "--cpus", "1", "--pids-limit", "64",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m", "--user", "65534:65534",
    ]
    if not allow_network:
        cmd += ["--network", "none"]
    cmd += [image, "python", "-I", "-"]
    try:
        res = subprocess.run(cmd, input=code, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run([rt, "kill", name], capture_output=True)
        raise SandboxError(f"Python Sandbox: execution timed out after {timeout}s") from None
    return res.returncode, res.stdout, res.stderr


def _tool_venv(requirements: List[str]) -> str:
    """Python of a venv with the requirements installed, built once under <data dir>/tool-envs/."""
    if getattr(sys, "frozen", False):
        raise SandboxError("Python Sandbox: tools with requirements need the container sandbox in the desktop app "
                           "(install podman or Docker).")
    root = data_path("tool-envs", _env_key(f"{sys.version_info[0]}.{sys.version_info[1]}", requirements))
    python = os.path.join(root, "Scripts" if os.name == "nt" else "bin", "python")
    ready = os.path.join(root, ".ready")
    with _env_lock(root):
        if os.path.exists(ready):
            return python
        shutil.rmtree(root, ignore_errors=True)          # a half-built env from a failed attempt
        logger.info(f"Sandbox: creating venv for {' '.join(requirements)}")
        steps = [[sys.executable, "-m", "venv", root],
                 [python, "-m", "pip", "install", "--disable-pip-version-check", *requirements]]
        for cmd in steps:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_S,
                                     env=scrubbed_env())
            except subprocess.TimeoutExpired:
                shutil.rmtree(root, ignore_errors=True)
                raise SandboxError(f"Python Sandbox: installing {' '.join(requirements)} timed out") from None
            if res.returncode != 0:
                shutil.rmtree(root, ignore_errors=True)
                raise SandboxError("Python Sandbox: couldn't install the tool's requirements:\n"
                                   + _truncate((res.stderr or res.stdout).strip()[-4000:]))
        with open(ready, "w") as f:
            f.write(json.dumps(requirements))
    return python


def _local_command(timeout: int, memory_mb: int, python: Optional[str] = None) -> list:
    limits = [str(timeout + 1), str(memory_mb)]
    if python:
        return [python, "-I", "-c", _LOCAL_BOOTSTRAP, *limits]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--sandbox-exec", *limits]
    return [sys.executable, "-I", "-c", _LOCAL_BOOTSTRAP, *limits]


def _run_local(code: str, timeout: int, memory_mb: int,
               requirements: Optional[List[str]] = None) -> Tuple[int, str, str]:
    python = _tool_venv(requirements) if requirements else None
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    with tempfile.TemporaryDirectory(prefix="sbx_") as workdir:
        try:
            res = subprocess.run(
                _local_command(timeout, memory_mb, python),
                input=code, cwd=workdir, env=env,
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise SandboxError(f"Python Sandbox: execution timed out after {timeout}s") from None
    return res.returncode, res.stdout, res.stderr


def _run_remote(url: str, code: str, cfg: Dict[str, Any]) -> Tuple[int, str, str]:
    import httpx   # backend only; the runner image doesn't ship httpx

    # The runner may first build the requirements image, then runs the code
    timeout = max(1, int(cfg.get("timeout", 10))) + (INSTALL_TIMEOUT_S if cfg.get("requirements") else 0) + 30
    try:
        resp = httpx.post(f"{url}/run", json={"code": code, "cfg": cfg}, timeout=timeout,
                          headers={"Authorization": f"Bearer {os.environ.get('SANDBOX_TOKEN', '')}"})
    except httpx.TimeoutException:
        raise SandboxError("Python Sandbox: the sandbox runner didn't answer in time") from None
    except httpx.HTTPError as e:
        raise SandboxError(f"Python Sandbox: can't reach the sandbox runner at {url} ({type(e).__name__})") from None
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code == 200:
        return int(data.get("returncode", 1)), str(data.get("stdout", "")), str(data.get("stderr", ""))
    if resp.status_code == 401:
        raise SandboxError("Python Sandbox: the sandbox runner refused SANDBOX_TOKEN")
    raise SandboxError(str(data.get("error") or f"Python Sandbox: sandbox runner returned HTTP {resp.status_code}"))


def _execute(code: str, cfg: Dict[str, Any], allow_remote: bool = True) -> Tuple[int, str, str]:
    """Run code on the configured backend; returns (returncode, stdout, stderr).
    ``allow_remote=False`` (the runner itself) ignores SANDBOX_URL."""
    backend = str(cfg.get("backend", "auto")).lower()
    timeout = max(1, int(cfg.get("timeout", 10)))
    memory_mb = max(32, int(cfg.get("memory_mb", 256)))
    image = str(cfg.get("image") or DEFAULT_IMAGE)
    allow_network = bool(cfg.get("allow_network", False))
    try:
        requirements = normalize_requirements(cfg.get("requirements"))
    except ValueError as e:
        raise SandboxError(f"Python Sandbox: {e}") from None

    if backend == "local":
        return _run_local(code, timeout, memory_mb, requirements)

    url = remote_url() if allow_remote else ""
    if backend == "remote" and not url:
        raise SandboxError("Python Sandbox: backend 'remote' selected but SANDBOX_URL isn't set.")
    if url:   # remote, container or auto
        return _run_remote(url, code, {**cfg, "requirements": requirements})

    rt = _container_runtime()
    if backend == "container":
        if not rt:
            raise SandboxError("Python Sandbox: backend 'container' selected but no reachable podman/docker engine.")
        return _run_container(rt, code, timeout, memory_mb, image, allow_network, requirements)

    # auto
    if rt:
        return _run_container(rt, code, timeout, memory_mb, image, allow_network, requirements)
    if isolation_required():
        raise SandboxError("Python Sandbox: no container engine available and SANDBOX_REQUIRE_ISOLATION is set.")
    logger.warning("Sandbox: no container engine reachable — running Python in a local subprocess (no isolation)")
    return _run_local(code, timeout, memory_mb, requirements)


def _run_python_sync(code: str, cfg: Dict[str, Any]) -> str:
    try:
        return _format(*_execute(code, cfg))
    except SandboxError as e:
        return str(e)


async def run_python(code: str, cfg: Dict[str, Any]) -> str:
    try:
        return await asyncio.to_thread(_run_python_sync, code, cfg or {})
    except Exception as e:
        return f"Python Sandbox Error: {e}"


async def run_tool(code: str, input_text: str, config: Dict[str, Any], cfg: Dict[str, Any],
                   entrypoint: Optional[str] = None, args: Optional[Dict[str, Any]] = None,
                   takes_config: bool = True) -> str:
    """Call a custom tool in the sandbox and return its result: run(input_text, config), or with
    ``args`` the typed ``entrypoint(**args)`` (plus ``config=`` when it takes one). A result that
    isn't a string comes back as JSON.

    Raises RuntimeError with a user-facing message when the tool fails or can't run.
    """
    request = json.dumps({"code": code, "input_text": input_text, "config": config or {}, "entrypoint": entrypoint,
                          "args": args, "takes_config": takes_config}, default=str)
    try:
        returncode, stdout, stderr = await asyncio.to_thread(_execute, _TOOL_HARNESS % request, cfg)
    except SandboxError as e:
        raise RuntimeError(str(e)) from None
    try:
        reply = json.loads(stdout)
    except ValueError:  # the process died (exit, crash, rlimit) or wrote to the real stdout
        raise RuntimeError("Tool process failed:\n" + _truncate(stderr or stdout or f"exit code {returncode}")) from None
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return _truncate(reply["result"])
