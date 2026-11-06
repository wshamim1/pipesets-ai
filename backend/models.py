import os
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# Jan (jan.ai) desktop app's local OpenAI-compatible server — the address the LLM backends use
# when neither the node nor Settings → Model backends gives one.
JAN_DEFAULT_BASE = os.getenv("JAN_API_BASE", "http://127.0.0.1:1337/v1")


# ── LLM ──────────────────────────────────────────────────────────────────────

class LLMConfig(BaseModel):
    provider: str = Field(default="openai", description="openai | anthropic | ollama | llamacpp | jan | mock")
    model: str = Field(default="gpt-4", description="Model identifier")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: int = Field(default=1024, ge=1, le=32768, description="Max response tokens")
    top_p: float = Field(default=1.0, ge=0.0, le=1.0, description="Top-p nucleus sampling")
    api_key: Optional[str] = Field(default=None, description="API Key for the provider")
    system_prompt: Optional[str] = Field(
        default="You are a helpful and concise AI assistant built on Pipesets AI.",
        description="System prompt",
    )
    base_url: Optional[str] = Field(
        default=None, description="Custom base URL for Ollama/llama.cpp/Jan/vLLM/OpenAI-compatible APIs"
    )
    timeout_ms: int = Field(default=45000, ge=1000, le=300000, description="Per-call timeout in milliseconds")
    max_retries: int = Field(default=1, ge=0, le=5, description="Retry count before failing")
    retry_backoff_ms: int = Field(default=500, ge=0, le=10000, description="Backoff between retries in milliseconds")
    fallback_provider: Optional[str] = Field(default=None, description="Optional fallback provider")
    fallback_model: Optional[str] = Field(default=None, description="Optional fallback model")
    fallback_api_key: Optional[str] = Field(default=None, description="Optional fallback API key")
    fallback_base_url: Optional[str] = Field(default=None, description="Optional fallback base URL")


class ProviderValidateRequest(BaseModel):
    provider: str = Field(..., description="Provider id, e.g. openai | anthropic | ollama")
    model: Optional[str] = Field(default=None, description="Model to probe")
    api_key: Optional[str] = Field(default=None, description="Provider API key")
    base_url: Optional[str] = Field(default=None, description="Optional provider base URL")


class ProviderValidateResponse(BaseModel):
    provider: str
    model: str
    ok: bool
    message: str
    latency_ms: int = 0


class ProviderBulkValidateRequest(BaseModel):
    credentials: Dict[str, str] = Field(default_factory=dict, description="provider -> api key")
    models: Dict[str, str] = Field(default_factory=dict, description="provider -> model")


def make_default_config() -> LLMConfig:
    return LLMConfig(
        provider=os.getenv("DEFAULT_LLM_PROVIDER", "openai"),
        model=os.getenv("DEFAULT_LLM_MODEL", "gpt-4"),
        temperature=float(os.getenv("DEFAULT_LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("DEFAULT_LLM_MAX_TOKENS", "1024")),
        top_p=float(os.getenv("DEFAULT_LLM_TOP_P", "1.0")),
        api_key=os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or "",
        system_prompt="You are a helpful and concise AI assistant built on Pipesets AI.",
        base_url=os.getenv("LLM_BASE_URL", ""),
    )


# ── Apps ──────────────────────────────────────────────────────────────────────

class AppCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Application name")
    description: Optional[str] = Field(default="", description="Application description")
    flow_data: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Nodes, edges, and configs"
    )


class AppUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    flow_data: Optional[Dict[str, Any]] = None


class AppRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class AppDocsUpdateRequest(BaseModel):
    docs: str = Field(default="", max_length=100_000)


class AppDocsGenerateRequest(BaseModel):
    flow_data: Dict[str, Any]                     # live canvas nodes + edges (may be unsaved)
    app_id: str = ""
    name: str = ""
    description: str = ""
    example_prompts: List[str] = Field(default_factory=list)
    provider_keys: Dict[str, str] = Field(default_factory=dict)


class AppResponse(BaseModel):
    id: str
    tenant_id: str = 'tenant_demo'
    project_id: str = 'proj_research'
    owner_user_id: str = 'user_admin'
    name: str
    description: str
    flow_data: Dict[str, Any]
    status: str = "draft"           # draft | published
    version: int = 0                # 0 = never published, 1+ = published version
    docs: str = ""                  # Markdown README for the pipeline
    created_at: str
    updated_at: str
    publish_gate: Optional[Dict[str, Any]] = None   # eval gate result, on publish responses only


# ── Tools ─────────────────────────────────────────────────────────────────────

class ToolRunRequest(BaseModel):
    tool_type: str
    input_text: str
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ToolRunResponse(BaseModel):
    success: bool
    output: str
    tool_type: str


# ── Run ───────────────────────────────────────────────────────────────────────

class PromptRunRequest(BaseModel):
    prompt: str
    retrieval_query: Optional[str] = Field(default=None, description="Query used for RAG retrieval instead of the full prompt")
    config: Optional[LLMConfig] = None
    app_id: Optional[str] = None
    node_id: Optional[str] = None
    attached_tools: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    attached_skills: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Skills attached to the node")
    session_id: Optional[str] = Field(default=None, description="Memory session ID")
    memory_config: Optional[Dict[str, Any]] = Field(default=None, description="Memory node config")
    cache_config: Optional[Dict[str, Any]] = Field(default=None, description="Cache node config")
    retriever_config: Optional[Dict[str, Any]] = Field(default=None, description="Retriever node config for RAG")
    middleware_configs: Optional[List[Dict[str, Any]]] = Field(default=None, description="List of middleware node configs [{type, config, enabled}]")
    output_parser: Optional[Dict[str, Any]] = Field(default=None, description="Output parser node config {parser_type, schema_json, strict}")
    # Checkpointed runs (services/llm_checkpoint.py): a client-chosen id saves each step, so the
    # run can be resumed by re-sending the same request with resume_from set to that id
    run_id: Optional[str] = Field(default=None, max_length=64)
    resume_from: Optional[str] = Field(default=None, max_length=64)
    # Checkpointer node config {save_steps, restore_on_resume} (services/checkpoint.options)
    checkpoint: Optional[Dict[str, Any]] = None
    # Step-through debugging from the editor (services/debug_run.py):
    # {breakpoints: [node id], step: bool, overrides: {step key: {...}}, pins: {node id: output}}
    debug: Optional[Dict[str, Any]] = None
    # Skills (services/skills_runtime.py): "on_demand" (default; the model loads a skill with
    # use_skill and its tools switch on then) or "always" (every skill's instructions in the prompt)
    skill_mode: Optional[str] = Field(default=None, pattern="^(on_demand|always)$")
    max_active_skills: Optional[int] = Field(default=None, ge=1, le=10)


class PromptRunResponse(BaseModel):
    success: bool
    provider: str
    model: str
    output: str
    tools_used: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Prompt Build / Blueprint Generation ─────────────────────────────────────

class PromptBuildRequest(BaseModel):
    prompt: str
    mode: str = Field(default='auto', description='auto | tool | mcp | pipeline')
    config: Optional[LLMConfig] = None


class PromptBuildResponse(BaseModel):
    success: bool
    intent: str
    blueprint: Dict[str, Any] = Field(default_factory=dict)
    simulated: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None
    message: str = ''


class CodeImportRequest(BaseModel):
    code: str = Field(description="Existing code to convert (LangChain, CrewAI, raw Python, etc.)")
    framework_hint: str = Field(default='auto', description='auto | langchain | crewai | autogen | python | other')
    config: Optional[LLMConfig] = None


# ── Retrieval / RAG ───────────────────────────────────────────────────────────

class DocLoaderConfig(BaseModel):
    loader_type: str = Field(default="pdf", description="pdf | text | markdown | csv | json | docx | html | directory | web_url | sitemap | rss | youtube | wikipedia | arxiv | s3 | gcs | azure_blob | google_drive | sharepoint | postgres | mysql | mongodb | confluence | jira | notion | github | slack | excel | pptx | tsv | xml | epub | rtf | odt | rst | org_mode | email | notebook | python | toml | srt | bibtex | image | unstructured | textract | azure_doc_intelligence | recursive_url | firecrawl | spider | playwright | selenium | browserless | browserbase | scrapfly | scrapingant | gitbook | docusaurus | readthedocs | mhtml | news_url | brave_search | hacker_news | reddit | twitter | mastodon | bilibili | pubmed | gutenberg | ifixit | mediawiki_dump | dropbox | onedrive | tencent_cos | huawei_obs | baidu_bos | lakefs | obsidian | joplin | roam | acreom | evernote | quip | trello | figma | airtable | github_issues | bigquery | snowflake | sql_database | duckdb | athena | glue_catalog | couchbase | cassandra | astradb | dataframe | hf_dataset | stripe | hubspot | salesforce | shopify | zendesk | airbyte | datadog_logs | discord | telegram | whatsapp | facebook_chat | chatgpt | assemblyai | etherscan | weather | huggingface_model")
    loader_class: str = Field(default="", description="Custom loaders (loader_type starting with 'custom_'): import path / class name of the loader")
    loader_kwargs: str = Field(default="", description="Custom loaders: JSON object of constructor kwargs")
    source: str = Field(default="", description="File path, URL, S3 URI, or connection string")
    chunk_strategy: str = Field(default="fixed", description="fixed | paragraph | sentence")


class TextSplitterConfig(BaseModel):
    splitter_type: str = Field(default="recursive_character", description="recursive_character | token | markdown")
    chunk_size: int = Field(default=512, ge=32, le=8192)
    chunk_overlap: int = Field(default=50, ge=0, le=2048)


class EmbeddingConfig(BaseModel):
    provider: str = Field(default="local", description="openai | local")
    model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    api_key: Optional[str] = Field(default=None)


class VectorStoreConfig(BaseModel):
    store_type: str = Field(default="chroma", description="chroma | pgvector | pinecone")
    collection_name: str = Field(default="my_documents")
    connection_string: Optional[str] = Field(default=None)
    top_k: int = Field(default=5, ge=1, le=50)


# ── Cache ─────────────────────────────────────────────────────────────────────

class CacheEntryResponse(BaseModel):
    cache_key: str
    scope: str
    model: str
    provider: str
    hit_count: int
    created_at: str
    expires_at: str
    output_preview: str


# ── Memory ────────────────────────────────────────────────────────────────────

class MemoryMessage(BaseModel):
    role: str = Field(..., description="user | assistant | system")
    content: str
    token_count: int = Field(default=0)
    created_at: str = Field(default="")


class MemorySessionResponse(BaseModel):
    session_id: str
    messages: List[MemoryMessage]
    total_tokens: int
    strategy: str
    token_budget: int


# ── Traces ────────────────────────────────────────────────────────────────────

class TraceRecord(BaseModel):
    id: str
    run_id: str
    app_id: Optional[str] = None
    node_id: Optional[str] = None
    node_type: str = "llm"
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    attempt_count: int = 1
    used_fallback: int = 0
    effective_provider: Optional[str] = None
    effective_model: Optional[str] = None
    status: str = "success"
    error: Optional[str] = None
    prompt_preview: Optional[str] = None
    output_preview: Optional[str] = None
    metadata_json: Optional[str] = None
    spans_json: Optional[str] = None
    created_at: str


# ── Skills ────────────────────────────────────────────────────────────────────

class SkillCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Skill name")
    icon: str = Field(default="⚡", description="Emoji or icon")
    when_to_use: Optional[str] = Field(default=None, description="What the model reads to decide to load it (≤ 300 chars)")
    description: str = Field(default="", description="Older name for when_to_use")
    instructions: str = Field(default="", description="Detailed instructions, prompt guidance, or SOP")
    required_tools: Optional[List[str]] = Field(default=None, description="Tool / MCP server ids the skill uses")
    tool_ids: List[str] = Field(default_factory=list, description="Older name for required_tools")
    required_connections: List[str] = Field(default_factory=list, description="Connection types its tools need")
    tags: List[str] = Field(default_factory=list, description="Categorisation tags")
    category: str = Field(default="general", description="Skill category, e.g. analysis, coding, research")


class SkillUpdateRequest(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    when_to_use: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    required_tools: Optional[List[str]] = None
    tool_ids: Optional[List[str]] = None
    required_connections: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    category: Optional[str] = None


class SkillResponse(BaseModel):
    id: str
    tenant_id: str = "tenant_demo"
    project_id: str = "proj_research"
    owner_user_id: str = "user_admin"
    name: str
    icon: str = "⚡"
    description: str = ""
    instructions: str = ""
    tool_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    category: str = "general"
    builtin: bool = False
    when_to_use: str = ""
    required_tools: List[str] = Field(default_factory=list)
    required_connections: List[str] = Field(default_factory=list)
    version: int = 1
    available: bool = True   # built-ins: their tools are installed in this workspace
    created_at: str
    updated_at: str

