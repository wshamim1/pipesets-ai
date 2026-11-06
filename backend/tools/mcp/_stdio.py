"""Generic stdio runner for built-in MCP servers.

Each server module (tools/mcp/<category>/<id>.py) declares its launch command and a
``prepare()`` that maps node config to launch args / env vars and the MCP tool call, then
exposes ``run = stdio_server(COMMAND, ARGS, DEFAULT_TOOL, prepare)``.

``required`` names config keys the server can't start without (the ToolSpec's ``required``); a
missing one is named before anything is launched. A key is also satisfied by the environment
variable of the same name in upper case (``tavily_api_key`` → ``TAVILY_API_KEY``).

``run.discover(config)`` lists the server's tools with their input schemas (``tools/list``). A node
that stores them (``mcp_tools`` in its config) gets each one offered to the model as its own
function; a call then sets ``tool_name`` and ``arguments``, which every ``prepare()`` honours.
"""

import asyncio
import json
import os
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from services.child_env import scrubbed_env

STARTUP_TIMEOUT = 45.0
CALL_TIMEOUT = 30.0

Prepare = Callable[[Dict[str, Any], str, list, Dict[str, Any], Dict[str, Any]], Tuple[list, str, Dict[str, Any]]]


def missing_key(cfg: Dict[str, Any], required: Sequence[str]) -> Optional[str]:
    """The first required key with no value in ``cfg`` or the environment, if any."""
    return next((k for k in required if not str(cfg.get(k) or "").strip() and not os.environ.get(k.upper())), None)


def config_value(cfg: Dict[str, Any], key: str, default: str = "") -> str:
    """``cfg[key]``, else the ``KEY`` environment variable, else ``default``."""
    return str(cfg.get(key) or os.environ.get(key.upper()) or default).strip()


def stdio_server(command: str, args: List[str], default_tool: str, prepare: Optional[Prepare] = None,
                 required: Sequence[str] = ()):
    """Build a registry ``run`` that launches this server over stdio and calls one tool."""
    defaults = {"command": command, "args": list(args), "default_tool": default_tool}

    async def run(inp: str, cfg: Dict[str, Any], tool_type: str) -> str:
        missing = missing_key(cfg, required)
        if missing:
            return f"[{tool_type}] Set {missing} in the node's Parameters & Auth first."
        return await execute_stdio(tool_type, inp, cfg, defaults, prepare)

    async def discover(cfg: Dict[str, Any], tool_type: str = "") -> List[Dict[str, Any]]:
        missing = missing_key(cfg, required)
        if missing:
            raise RuntimeError(f"[{tool_type}] Set {missing} to list this server's tools.")
        return await discover_stdio(tool_type, cfg, defaults, prepare)

    run.discover = discover
    return run


async def not_configured(inp: str, cfg: Dict[str, Any], tool_type: str) -> str:
    """For catalog MCP servers that have no built-in launcher yet."""
    return (
        f"[MCP {tool_type}]\n"
        f"Transport: stdio  Input: {inp[:200]}\n"
        f"Note: Add this server via the Custom MCP panel and configure its command."
    )


class MCPStartError(RuntimeError):
    """The server couldn't be started or didn't finish the handshake; the message says why."""


def _launch(config: Dict[str, Any], input_text: str, defaults: Dict[str, Any], prepare: Optional[Prepare]):
    """(command path, args, env, tool name, call arguments) for this node config."""
    import shutil as _shutil

    args: list = list(defaults.get("args", []))
    env_vars: Dict[str, Any] = {}
    if prepare is not None:
        args, tool_name, call_args = prepare(config, input_text, args, env_vars, defaults)
    else:
        # Generic fallback for a server without its own prepare()
        tool_name = config.get("tool_name") or defaults.get("default_tool", "query")
        call_args = config.get("arguments") or {"input": input_text.strip()}
    command: str = defaults.get("command", "npx")
    return _shutil.which(command) or command, args, scrubbed_env(env_vars), tool_name, call_args


async def _read_json_rpc(reader):
    while True:
        line = await reader.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    return None


async def _stop(proc) -> None:
    """Terminate the server and reap it (an unreaped process is cleaned up after the loop closes)."""
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (ProcessLookupError, asyncio.TimeoutError):
        pass


async def _send(proc, message: Dict[str, Any]) -> None:
    proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
    await proc.stdin.drain()


async def _start(tool_type: str, cmd_path: str, args: list, env: Dict[str, str], startup_timeout: float):
    """Spawn the server and complete the handshake; returns the process. Raises MCPStartError."""
    try:
        proc = await asyncio.create_subprocess_exec(cmd_path, *args, stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                    env=env)
    except Exception as e:
        raise MCPStartError(f"[{tool_type}] Failed to start MCP process: {e}")
    try:
        await _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "pipesets-ai", "version": "1.0.0"}}})
        started = await asyncio.wait_for(_read_json_rpc(proc.stdout), timeout=startup_timeout)
    except asyncio.TimeoutError:
        await _stop(proc)
        raise MCPStartError(f"[{tool_type}] MCP server didn't start within {startup_timeout:g}s. The first run may "
                            f"still be downloading packages — try again, or raise startup_timeout in the node config.")
    if started is None:  # the process exited before answering the handshake
        err = (await proc.stderr.read()).decode("utf-8", errors="replace").strip()
        await _stop(proc)
        raise MCPStartError(f"[{tool_type}] MCP server exited during startup: {err[-500:] or 'no output'}")
    await _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    return proc


async def discover_stdio(tool_type: str, config: Dict[str, Any], defaults: Dict[str, Any],
                         prepare: Optional[Prepare]) -> List[Dict[str, Any]]:
    """The server's tools — [{name, description, inputSchema}] — with this node config's launch
    args and env. Raises MCPStartError, or RuntimeError when tools/list fails."""
    startup_timeout = float(config.get("startup_timeout") or STARTUP_TIMEOUT)
    cmd_path, args, env, _, _ = _launch(config, "", defaults, prepare)
    proc = await _start(tool_type, cmd_path, args, env, startup_timeout)
    try:
        await _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        res = await asyncio.wait_for(_read_json_rpc(proc.stdout), timeout=float(config.get("call_timeout") or CALL_TIMEOUT))
    except asyncio.TimeoutError:
        raise RuntimeError(f"[{tool_type}] The server didn't list its tools in time")
    finally:
        await _stop(proc)
    if not res or "result" not in res:
        raise RuntimeError(f"[{tool_type}] tools/list failed: {(res or {}).get('error', 'no answer')}")
    return tool_listing(res["result"])


def tool_listing(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A tools/list result as [{name, description, inputSchema}]."""
    return [{"name": t.get("name"), "description": t.get("description", ""), "inputSchema": t.get("inputSchema") or {}}
            for t in result.get("tools", []) if isinstance(t, dict) and t.get("name")]


def call_result_text(label: str, call_res: Optional[Dict[str, Any]]) -> str:
    """A tools/call reply as the text the model sees."""
    if call_res and "result" in call_res:
        content = call_res["result"].get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and "text" in c]
            return "\n".join(texts) if texts else json.dumps(call_res["result"], indent=2)
        return str(call_res["result"])
    if call_res and "error" in call_res:
        return f"[{label}] MCP error: {call_res['error'].get('message', call_res['error'])}"
    return f"[{label}] Completed with no output."


async def execute_stdio(tool_type: str, input_text: str, config: Dict[str, Any],
                        defaults: Dict[str, Any], prepare: Optional[Prepare]) -> str:
    """Start the server, do the JSON-RPC handshake, call one tool and return its text output.

    Config keys recognised for every server:
      - tool_name        override which MCP tool to invoke
      - arguments        dict of tool arguments (default depends on the server)
      - startup_timeout  seconds to wait for the server to start (default 45 — npx/uvx may
                         download and build packages on a cold start)
      - call_timeout     seconds to wait for the tool call (default 30)
    """
    startup_timeout = float(config.get("startup_timeout") or STARTUP_TIMEOUT)
    call_timeout = float(config.get("call_timeout") or CALL_TIMEOUT)
    cmd_path, args, env, tool_name, call_args = _launch(config, input_text, defaults, prepare)
    try:
        proc = await _start(tool_type, cmd_path, args, env, startup_timeout)
    except MCPStartError as e:
        return str(e)

    try:
        await _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": tool_name, "arguments": call_args}})
        call_res = await asyncio.wait_for(_read_json_rpc(proc.stdout), timeout=call_timeout)
        await _stop(proc)
        return call_result_text(tool_type, call_res)

    except asyncio.TimeoutError:
        await _stop(proc)
        return f"[{tool_type}] Timed out after {call_timeout:g}s waiting for the tool call."
    except Exception as e:
        await _stop(proc)
        return f"[{tool_type}] Error: {e}"
