import json
import re
from typing import Any, Dict, List

from fastapi import APIRouter

import loaders as doc_loaders
import tools as tool_registry
from models import LLMConfig, PromptBuildRequest, PromptBuildResponse, CodeImportRequest
from routers.run import _can_attempt_real_call, _completion_with_policy, get_current_config

router = APIRouter(tags=['build'])


def _detect_intent(prompt: str, mode: str) -> str:
    if mode != 'auto':
        return mode
    s = prompt.lower()
    mcp_score = int(bool(re.search(r'\bmcp\b|server|stdio|sse|transport|endpoint', s)))
    tool_score = int(bool(re.search(r'\btool\b|function|python|script|api|connector', s)))
    pipe_score = int(bool(re.search(r'pipeline|workflow|flow|agent|rag|orchestrat|sequence|multi[ -]?step', s)))
    if mcp_score >= tool_score and mcp_score >= pipe_score and mcp_score > 0:
        return 'mcp'
    if tool_score >= pipe_score and tool_score > 0:
        return 'tool'
    return 'pipeline'


def _fallback_blueprint(intent: str, prompt: str) -> Dict[str, Any]:
    base_nodes = [
        {
            'id': 'start',
            'type': 'start',
            'position': {'x': 220, 'y': 260},
            'data': {'label': 'Start'},
        },
        {
            'id': 'llm',
            'type': 'llm',
            'position': {'x': 520, 'y': 250},
            'data': {
                'label': 'Prompt Planner',
                'provider': 'openai',
                'model': 'gpt-4o',
                'temperature': 0.5,
                'max_tokens': 1024,
                'top_p': 1.0,
                'api_key': '',
                'system_prompt': f'You are an orchestration assistant. Goal: {prompt}',
                'base_url': '',
                'timeout_ms': 45000,
                'max_retries': 1,
                'retry_backoff_ms': 500,
                'fallback_provider': '',
                'fallback_model': '',
                'fallback_api_key': '',
                'fallback_base_url': '',
            },
        },
        {
            'id': 'stop',
            'type': 'stop',
            'position': {'x': 840, 'y': 260},
            'data': {'label': 'Stop'},
        },
    ]
    return {
        'label': f'{intent.title()} Blueprint',
        'nodes': base_nodes,
        'edges': [
            {'id': 'edge-start-llm', 'source': 'start', 'target': 'llm'},
            {'id': 'edge-llm-stop', 'source': 'llm', 'target': 'stop'},
        ],
        'selected_node_id': 'llm',
    }


def _extract_json_object(text: str) -> Dict[str, Any] | None:
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```[a-zA-Z]*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else None
    except Exception:
        pass

    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    snippet = text[start:end + 1]
    try:
        val = json.loads(snippet)
        return val if isinstance(val, dict) else None
    except Exception:
        return None


def _tool_names() -> List[str]:
    return sorted(s.id for s in tool_registry.all_specs() if not s.hidden)


_TOOL_SYSTEM_PROMPT = (
    'You write custom Python tools for Pipesets AI. '
    'Return ONLY a JSON object; no markdown, no prose. '
    'Schema: {"name": string (2-4 words, Title Case), "icon": one emoji, "description": one sentence, '
    '"code": string, "config_keys": array of strings, "packages": array of pip package names}. '
    'The code must define the entry point def run(input_text: str, config: dict) -> str. '
    'input_text is the calling agent\'s request in plain language (or a simple argument); parse it defensively. '
    'Read every credential, host and setting from config (e.g. config["api_key"]); never hard-code secrets, '
    'and list each key the code reads in config_keys. '
    'Prefer the Python standard library or requests over heavy SDKs; list any third-party package in packages. '
    'Make real API calls: no placeholders, stubs or TODOs. '
    'Catch exceptions and return a short readable error string instead of raising. '
    'Return results as concise text an LLM can read (a JSON string is fine).'
)


async def _generate_tool(prompt: str, cfg: LLMConfig) -> PromptBuildResponse:
    """Ask the model for a ready-to-test custom tool; blueprint={} means use the local template."""
    if not _can_attempt_real_call(cfg):
        return PromptBuildResponse(
            success=True, intent='tool', simulated=True, provider=cfg.provider, model=cfg.model,
            message=f'No API key for {cfg.provider}, so only a template was drafted. Add a key in Settings to generate real code.',
        )
    # Tool code needs more room than the canvas LLM node's default max_tokens.
    cfg = cfg.model_copy(update={'max_tokens': max(int(cfg.max_tokens or 0), 2500), 'temperature': 0.2})
    messages = [{'role': 'system', 'content': _TOOL_SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}]
    try:
        completion, active_cfg, _, used_fallback = await _completion_with_policy(cfg, messages)
    except Exception as e:
        return PromptBuildResponse(
            success=True, intent='tool', simulated=True, provider=cfg.provider, model=cfg.model,
            message=f'Live generation failed: {e}. Drafted a template instead.',
        )

    parsed = _extract_json_object(completion.text) or {}
    code = parsed.get('code') if isinstance(parsed.get('code'), str) else ''
    problem = ''
    if 'def run(' not in code:
        problem = 'The model did not return a run() function'
    else:
        try:
            compile(code, '<generated tool>', 'exec')
        except SyntaxError as e:
            problem = f'The generated code has a syntax error (line {e.lineno}: {e.msg})'
    if problem:
        return PromptBuildResponse(
            success=True, intent='tool', simulated=True, provider=active_cfg.provider, model=active_cfg.model,
            message=f'{problem}. Drafted a template instead — try Generate again.',
        )

    def str_list(v: Any) -> List[str]:
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    return PromptBuildResponse(
        success=True, intent='tool', simulated=bool(used_fallback),
        provider=active_cfg.provider, model=active_cfg.model,
        message='Generated tool code from live model.',
        blueprint={
            'name': str(parsed.get('name') or '').strip()[:60],
            'icon': str(parsed.get('icon') or '🔧').strip()[:4],
            'description': str(parsed.get('description') or '').strip(),
            'code': code.rstrip() + '\n',
            'config_keys': str_list(parsed.get('config_keys')),
            'packages': str_list(parsed.get('packages')),
        },
    )


@router.post('/api/build/generate', response_model=PromptBuildResponse)
async def generate_blueprint(req: PromptBuildRequest):
    prompt = req.prompt.strip()
    if not prompt:
        return PromptBuildResponse(
            success=False,
            intent='pipeline',
            message='Prompt cannot be empty.',
            blueprint={},
        )

    intent = _detect_intent(prompt, req.mode)
    cfg = req.config or get_current_config()

    if intent == 'tool':
        return await _generate_tool(prompt, cfg)

    # MCP drafts are still assembled in the frontend.
    if intent == 'mcp':
        return PromptBuildResponse(
            success=True,
            intent=intent,
            simulated=True,
            provider=cfg.provider,
            model=cfg.model,
            message=f'{intent.upper()} intent detected. Use frontend draft modal for detailed editing.',
            blueprint={},
        )

    if not _can_attempt_real_call(cfg):
        return PromptBuildResponse(
            success=True,
            intent='pipeline',
            simulated=True,
            provider=cfg.provider,
            model=cfg.model,
            message='No live key available for this provider. Returned fallback scaffold.',
            blueprint=_fallback_blueprint('pipeline', prompt),
        )

    messages: List[Dict[str, str]] = [
        {
            'role': 'system',
            'content': (
                'You are a pipeline architect for Pipesets AI. '
                'Return ONLY valid JSON object; no markdown, no prose. '
                'Build a practical pipeline from a user prompt. '
                'Node types allowed: start, stop, llm, tool, toolkit, memory, cache, doc_loader, text_splitter, embedding, vector_store, retriever, master_agent, child_agent, gateway. '
                'Each node: id (string), type, position {x,y}, data object with sensible defaults. '
                'Each edge: id, source, target. '
                'Must include at least start and stop. '
                'For llm data include: label, provider, model, temperature, max_tokens, top_p, api_key, system_prompt, base_url, timeout_ms, max_retries, retry_backoff_ms, fallback_provider, fallback_model, fallback_api_key, fallback_base_url. '
                'For tool node include: label, toolId, toolType, icon, description, config. '
                'For master_agent include provider/model/api fields and strategy/max_steps. '
                'If user asks for RAG, include doc_loader -> text_splitter -> embedding -> vector_store -> retriever -> llm path. '
                'If user asks for multi-agent, include master_agent and at least 2 child_agent nodes connected to master. '
                f'Available tool IDs: {", ".join(_tool_names())}. '
                'Output schema: {"label": string, "nodes": array, "edges": array, "selected_node_id": string}.'
            ),
        },
        {'role': 'user', 'content': prompt},
    ]

    try:
        completion, active_cfg, _, used_fallback = await _completion_with_policy(cfg, messages)
        text = completion.text
        parsed = _extract_json_object(text)
        if not parsed:
            return PromptBuildResponse(
                success=True,
                intent='pipeline',
                simulated=True,
                provider=active_cfg.provider,
                model=active_cfg.model,
                message='Model response was not valid JSON. Returned fallback scaffold.',
                blueprint=_fallback_blueprint('pipeline', prompt),
            )

        nodes = parsed.get('nodes') if isinstance(parsed.get('nodes'), list) else []
        edges = parsed.get('edges') if isinstance(parsed.get('edges'), list) else []
        if len(nodes) < 2:
            parsed = _fallback_blueprint('pipeline', prompt)
            msg = 'Model returned incomplete blueprint. Returned fallback scaffold.'
            simulated = True
        else:
            msg = 'Generated pipeline blueprint from live model.'
            simulated = bool(used_fallback)

        return PromptBuildResponse(
            success=True,
            intent='pipeline',
            simulated=simulated,
            provider=active_cfg.provider,
            model=active_cfg.model,
            message=msg,
            blueprint=parsed,
        )
    except Exception as e:
        return PromptBuildResponse(
            success=True,
            intent='pipeline',
            simulated=True,
            provider=cfg.provider,
            model=cfg.model,
            message=f'Live generation failed: {e}. Returned fallback scaffold.',
            blueprint=_fallback_blueprint('pipeline', prompt),
        )


# ── Code → Pipeline importer ──────────────────────────────────────────────────

_FRAMEWORK_HINTS = {
    'langchain': 'LangChain',
    'crewai':    'CrewAI',
    'autogen':   'AutoGen / Microsoft AutoGen',
    'python':    'plain Python',
    'other':     'an unknown framework',
}

# Only loaders the backend can run, so generated pipelines never use a "coming soon" one
_AVAILABLE_LOADERS = "|".join(f'"{e["type"]}"' for e in doc_loaders.catalog() if e["available"])

_IMPORT_SYSTEM_PROMPT = (
    'You are a pipeline architect for Pipesets AI. '
    'The user will paste existing agent/LLM code (LangChain, CrewAI, AutoGen, plain Python, etc.). '
    'Analyse it and return a canvas pipeline blueprint that reproduces the same behaviour. '
    'Return ONLY a valid JSON object. No markdown, no prose, no code fences. '
    'Node types: start, stop, llm, tool, toolkit, memory, cache, doc_loader, text_splitter, '
    'embedding, vector_store, retriever, master_agent, child_agent, output_parser, gateway. '
    'Every node: id (string), type, position {{x,y}}, data object with sensible defaults. '
    'Every edge: id, source, target. '
    'Must include at least one start and one stop node. '
    'LLM node data: label, provider, model, temperature, max_tokens, top_p, api_key (empty string), '
    'system_prompt, base_url, timeout_ms, max_retries, retry_backoff_ms, '
    'fallback_provider, fallback_model, fallback_api_key, fallback_base_url. '
    'Tool node data: label, toolId, toolType ("tool"|"mcp"), icon, description, config (object). '
    'master_agent data: label, provider, model, api_key, strategy ("sequential"|"parallel"|"critic"), max_steps. '
    'child_agent data: label, provider, model, api_key, role, system_prompt, allowed_tool_ids (array). '
    'output_parser data: label, parser_type ("json"|"pydantic"|"csv"), schema_json, strict. '
    'memory data: label, strategy ("sliding_window"|"last_k"), token_budget, session_id, session_ttl_hours. '
    'doc_loader data: label, loader_type (EXACTLY one of ' + _AVAILABLE_LOADERS + '), '
    'source (file/directory path, full http(s):// URL for web_url/sitemap/rss/youtube, s3:// or gs:// URI, or a database connection string), chunk_strategy ("fixed"|"paragraph"|"sentence"). '
    'Mapping: WebBaseLoader->web_url, RecursiveUrlLoader->web_url, PyPDFLoader/PyMuPDFLoader->pdf, CSVLoader->csv, JSONLoader->json, TextLoader->text, '
    'UnstructuredMarkdownLoader->markdown, Docx2txtLoader->docx, DirectoryLoader->directory, SitemapLoader->sitemap, WikipediaLoader->wikipedia, ArxivLoader->arxiv. '
    'text_splitter data: label, splitter_type ("recursive_character"|"token"|"markdown"|"semantic"|"sentence"|"html"), chunk_size, chunk_overlap. '
    'embedding data: label, provider ("openai"|"local"|"cohere"|"google"|"azure_openai"|"mistral"|"ollama"|"llamacpp"|"bedrock"|"voyage"|"nomic"), model, api_key (empty string). '
    'vector_store data: label, store_type ("local"|"pgvector"; prefer "local"), collection_name (non-empty), connection_string, top_k. '
    'retriever data: label, search_type ("similarity"|"mmr"|"bm25_hybrid"|"multi_query"), collection_name (same as the vector_store), top_k, score_threshold, rerank, '
    'embedding_provider, embedding_model, embedding_api_key (empty string). '
    'RAG pattern: doc_loader -> text_splitter -> embedding -> vector_store -> retriever -> llm. '
    'Multi-agent pattern: master_agent connected to child_agent nodes. '
    'Layout nodes left-to-right, x spacing ~220, y centred ~260. '
    'Set selected_node_id to the primary LLM or master_agent node. '
    '{tool_hint}'
    'Output schema exactly: {{"label": string, "nodes": array, "edges": array, "selected_node_id": string}}'
)


def _detect_framework(code: str, hint: str) -> str:
    if hint != 'auto':
        return _FRAMEWORK_HINTS.get(hint, hint)
    c = code.lower()
    if 'from langchain' in c or 'langchain' in c:
        return 'LangChain'
    if 'crewai' in c or ('crew(' in c) or ('agent(' in c and 'task(' in c):
        return 'CrewAI'
    if 'autogen' in c or 'conversable_agent' in c:
        return 'AutoGen'
    return 'Python agent code'


@router.post('/api/build/import-code', response_model=PromptBuildResponse)
async def import_code_to_pipeline(req: CodeImportRequest):
    code = req.code.strip()
    if not code:
        return PromptBuildResponse(
            success=False,
            intent='pipeline',
            message='No code provided.',
            blueprint={},
        )

    cfg = req.config or get_current_config()
    framework = _detect_framework(code, req.framework_hint)
    tool_hint = (
        f'Available built-in tool IDs: {", ".join(_tool_names())}. '
        'Map code tools/APIs to the closest matching toolId where possible. '
    )

    system_content = _IMPORT_SYSTEM_PROMPT.format(tool_hint=tool_hint)
    user_content = (
        f'Convert this {framework} code to a Pipesets AI pipeline blueprint.\n\n'
        f'```\n{code[:12000]}\n```'
    )

    if not _can_attempt_real_call(cfg):
        return PromptBuildResponse(
            success=True,
            intent='pipeline',
            simulated=True,
            provider=cfg.provider,
            model=cfg.model,
            message='No live API key configured. Add an OpenAI (or other) key on the LLM node and retry.',
            blueprint=_fallback_blueprint('pipeline', f'Imported from {framework}'),
        )

    messages: List[Dict[str, str]] = [
        {'role': 'system', 'content': system_content},
        {'role': 'user',   'content': user_content},
    ]

    try:
        completion, active_cfg, _, used_fallback = await _completion_with_policy(cfg, messages)
        text = completion.text
        parsed = _extract_json_object(text)

        if not parsed or len(parsed.get('nodes', [])) < 2:
            return PromptBuildResponse(
                success=True,
                intent='pipeline',
                simulated=True,
                provider=active_cfg.provider,
                model=active_cfg.model,
                message=(
                    f'Could not parse a complete blueprint from the {framework} code. '
                    'Returned a starter scaffold — review and adjust nodes manually.'
                ),
                blueprint=_fallback_blueprint('pipeline', f'Imported from {framework}'),
            )

        return PromptBuildResponse(
            success=True,
            intent='pipeline',
            simulated=bool(used_fallback),
            provider=active_cfg.provider,
            model=active_cfg.model,
            message=f'Pipeline imported from {framework}. Review node configs and add your API keys.',
            blueprint=parsed,
        )
    except Exception as e:
        return PromptBuildResponse(
            success=True,
            intent='pipeline',
            simulated=True,
            provider=cfg.provider,
            model=cfg.model,
            message=f'Import failed: {e}. Returned starter scaffold.',
            blueprint=_fallback_blueprint('pipeline', f'Imported from {framework}'),
        )
