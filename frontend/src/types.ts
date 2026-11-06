import type { Node, Edge } from '@xyflow/react'
import type { ParamSchema } from './utils/toolParams'
import type { DocLoaderType } from './utils/docLoaders'

// The dev server opened from another host (an ngrok tunnel, a phone) proxies the API on its own
// origin (vite.config.ts); "localhost:8000" would point at the visiting device itself.
const isRemoteDev = import.meta.env.DEV && !['localhost', '127.0.0.1'].includes(window.location.hostname)

// The desktop app (desktop/) injects the address of the backend it started
export const API_BASE = (window as { __PIPESETS_API_BASE__?: string }).__PIPESETS_API_BASE__
  || import.meta.env.VITE_API_BASE || (isRemoteDev ? '' : 'http://localhost:8000')

// Where outside callers reach /v1 (API keys, webhook URLs). Behind the edge proxy that is the
// public API host, not the UI's own /api (deploy/edge); defaults to API_BASE.
export const PUBLIC_API_BASE = import.meta.env.VITE_PUBLIC_API_URL || API_BASE || window.location.origin

// ── Catalog types ─────────────────────────────────────────────────────────────

export interface ProviderOption {
  id: string
  name: string
  models: string[]
}

export interface ToolCatalogItem {
  id: string
  name: string
  type: 'tool' | 'mcp'
  icon: string
  description: string
  category?: string
  default_config: Record<string, any>
  /** Config keys the tool can't run without (from its backend spec). */
  required_config?: string[]
  /** Settings with a fixed set of choices, rendered as dropdowns. */
  config_options?: Record<string, ToolConfigSelect>
  /** JSON schema of the arguments the model calls it with (absent: one input string). */
  parameters?: ParamSchema
  /** Highlighted in the sidebar as newly added. */
  is_new?: boolean
  /** Built-in tools and MCP servers: installed in this workspace (Settings → Tools & MCP packages), so offered in the sidebar. */
  installed?: boolean
}

export interface ToolConfigSelect {
  label: string
  options: { value: string; label: string }[]
  hint?: string
}

export interface ToolCategory {
  id: string
  name: string
  tools: ToolCatalogItem[]
}

export interface ConnectionRecord {
  id: string
  name: string
  type: 'postgres' | 'mysql' | 'mongodb' | 'redis' | 'snowflake' | 'aws_s3' | 'sqlite' | 'custom_api'
  icon: string
  description: string
  config: Record<string, any>
  status: 'connected' | 'error' | 'untested'
  status_msg: string
  created_at: string
  updated_at: string
}

export interface KnowledgeBaseRecord {
  id: string
  name: string
  icon: string
  description: string
  source_type: 'text' | 'file' | 'web_url'
  source_detail: string
  embedding_provider: string
  embedding_model: string
  chunk_count: number
  created_at: string
  updated_at: string
}

export interface CustomMcpRecord {
  id: string
  name: string
  icon: string
  description: string
  transport: 'stdio' | 'sse' | 'http'
  command: string
  args: string[]
  env_vars: Record<string, string>
  url: string
  headers: Record<string, string>
  /** OAuth sign-in for remote servers; tokens themselves never reach the browser */
  oauth_status?: 'none' | 'connected' | 'expired'
  tools_cache: Array<{
    name: string
    description?: string
    inputSchema?: Record<string, any>
  }>
  created_at: string
  updated_at: string
}

export interface SkillRecord {
  id: string
  tenant_id?: string
  project_id?: string
  owner_user_id?: string
  name: string
  icon: string
  description: string
  instructions: string
  tool_ids: string[]
  tags: string[]
  category: string
  builtin?: boolean
  // Agent skills (plan.md C10): description is the "when to use" text, tool_ids the tools it needs
  when_to_use?: string
  required_tools?: string[]
  required_connections?: string[]
  version?: number
  available?: boolean   // built-ins: their tools are installed in this workspace
  created_at: string
  updated_at: string
}

// A sub-tool entry stored inside a ToolkitNode
export interface ToolkitSubTool {
  toolId: string
  toolType: 'tool' | 'mcp'
  label: string
  icon: string
  description: string
  config: Record<string, any>
}

export interface ToolkitCatalogItem {
  id: string
  name: string
  icon: string
  description: string
}

export interface AppRecord {
  id: string
  name: string
  description: string
  flow_data: {
    nodes?: FlowNode[]
    edges?: FlowEdge[]
  }
  status: 'draft' | 'published'   // draft | published
  version: number                  // 0 = never published, 1+ = published version
  docs?: string                    // Markdown README (Docs tab)
  created_at: string
  updated_at: string
}

export interface TraceRecord {
  id: string
  run_id: string
  app_id?: string
  node_id?: string
  node_type: string
  provider: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  latency_ms: number
  cost_usd: number
  attempt_count?: number
  used_fallback?: number | boolean
  effective_provider?: string
  effective_model?: string
  status: string
  error?: string
  prompt_preview?: string
  output_preview?: string
  metadata_json?: string
  spans_json?: string
  created_at: string
}

// ── Node data types ───────────────────────────────────────────────────────────

/** Editor-only debugging on a node (plan.md F6): a breakpoint pauses Prompt Runner runs before the
 *  node's steps; a pin is used instead of running the node. Published runs never read either. */
export type DebugPin = { output: string; pinned_at?: string }
export type DebugNodeFields = {
  debug_breakpoint?: boolean
  debug_pin?: DebugPin
  // Injected by the canvas (like onDelete), never saved: the node's own debug buttons
  onDebugUpdate?: (fields: Partial<Pick<DebugNodeFields, 'debug_breakpoint' | 'debug_pin'>>) => void
  onOpenDebug?: (editPin: boolean) => void
}

export type LlmNodeData = DebugNodeFields & {
  label: string
  provider: string
  model: string
  temperature: number
  max_tokens: number
  top_p: number
  api_key: string
  system_prompt: string
  base_url: string
  timeout_ms?: number
  max_retries?: number
  retry_backoff_ms?: number
  fallback_provider?: string
  fallback_model?: string
  fallback_api_key?: string
  fallback_base_url?: string
  skill_mode?: 'on_demand' | 'always'   // services/skills_runtime.py
  max_active_skills?: number
  isSelected?: boolean
  onDelete?: () => void
}

export type ToolNodeData = DebugNodeFields & {
  label: string
  toolId: string
  toolType: 'tool' | 'mcp'
  icon: string
  description: string
  config: Record<string, any>
  isSelected?: boolean
  onDelete?: () => void
}

export type ToolkitNodeData = DebugNodeFields & {
  label: string
  toolkitId: string
  icon: string
  description: string
  subTools: ToolkitSubTool[]
  isSelected?: boolean
  onDelete?: () => void
  onDropTool?: (tool: ToolCatalogItem) => void
}

export type MemoryNodeData = {
  label: string
  strategy: 'sliding_window' | 'summarize' | 'last_k' | 'vector' | 'knowledge_graph'
  token_budget: number
  session_id: string
  session_ttl_hours: number
  // Long-term memory: facts about the end user, recalled across sessions (when the tenant opts in)
  long_term?: boolean
  recall_k?: number
  extract_facts?: boolean
  isSelected?: boolean
  onDelete?: () => void
}

export type CacheNodeData = {
  label: string
  scope: 'prompt' | 'model' | 'strict'
  ttl_seconds: number
  max_size: number
  isSelected?: boolean
  onDelete?: () => void
}

export type DocLoaderNodeData = {
  label: string
  loader_type: DocLoaderType
  /** Custom loaders only: import path / class name of the loader. */
  loader_class?: string
  /** Custom loaders only: JSON object of constructor kwargs. */
  loader_kwargs?: string
  source: string
  db_table?: string
  db_query?: string
  /** Scanned pages / images (PDF, Image, Directory, S3, Email loaders): backend loaders/_ocr.py */
  ocr_engine?: 'auto' | 'ocrmypdf' | 'tesseract' | 'docling' | 'vision' | 'off'
  ocr_language?: string
  ocr_provider?: string
  ocr_model?: string
  chunk_strategy: 'fixed' | 'paragraph' | 'sentence'
  isSelected?: boolean
  onDelete?: () => void
}

export type TextSplitterNodeData = {
  label: string
  splitter_type: 'recursive_character' | 'token' | 'markdown' | 'semantic' | 'sentence' | 'html'
  chunk_size: number
  chunk_overlap: number
  isSelected?: boolean
  onDelete?: () => void
}

export type EmbeddingNodeData = {
  label: string
  provider: 'openai' | 'local' | 'anthropic' | 'cohere' | 'google' | 'azure_openai'
    | 'mistral' | 'ollama' | 'llamacpp' | 'bedrock' | 'voyage' | 'nomic'
  model: string
  api_key: string
  isSelected?: boolean
  onDelete?: () => void
}

/** Vector store backends the server implements (backend/services/vector_store.py). */
export const LIVE_VECTOR_STORES: ReadonlySet<string> = new Set(['local', 'pgvector'])

export type VectorStoreNodeData = {
  label: string
  store_type: 'local' | 'chroma' | 'pgvector' | 'pinecone' | 'weaviate' | 'qdrant' | 'milvus'
    | 'elasticsearch' | 'mongodb_atlas' | 'opensearch'
    | 'redis' | 'faiss' | 'azure_ai_search' | 'vertex_ai' | 'lancedb'
  collection_name: string
  connection_string: string
  top_k: number
  isSelected?: boolean
  onDelete?: () => void
}

export type RerankerNodeData = {
  label: string
  reranker_type: 'cohere' | 'cross_encoder' | 'flashrank' | 'bge'
  model: string
  api_key: string
  top_n: number
  isSelected?: boolean
  onDelete?: () => void
}

export type HumanGateNodeData = {
  label: string
  gate_type: 'approval' | 'edit' | 'review'
  prompt_message: string
  timeout_hours: number
  on_timeout: 'approve' | 'reject' | 'escalate'
  isSelected?: boolean
  onDelete?: () => void
}

/** Checkpointing for the whole run (services/checkpoint.options on the backend). */
export type CheckpointerNodeData = {
  label: string
  save_steps: boolean          // off: keep no model / tool output, only the run's status
  restore_on_resume: boolean   // off: a resume of an interrupted or failed run starts over
  isSelected?: boolean
  onDelete?: () => void
}

export type WorkflowStepType = 'ask' | 'choice' | 'confirm' | 'tool_call' | 'message'

/**
 * One step of a conversational workflow (e.g. "ask for a city, then look up its weather").
 * ask / choice / confirm pause the run and wait for the user; tool_call and message run straight through.
 * Values are stored in run variables and referenced elsewhere as {{variable}}.
 */
export type WorkflowStepNodeData = {
  label: string
  step_type: WorkflowStepType
  prompt: string            // message shown to the user (supports {{variable}})
  variable: string          // variable that receives the answer / result
  input_kind?: 'text' | 'number' | 'date'   // ask
  options_source?: string   // choice: variable holding the list to pick from
  option_label_field?: string  // choice: field shown on each option, e.g. "name"
  option_value_field?: string  // choice: field stored as the answer, e.g. "id"
  tool_id?: string          // tool_call: fallback tool id when no tool node is linked
  tool_input?: string       // tool_call: text sent to the tool, supports {{variable}} (e.g. "{{city}}")
  isSelected?: boolean
  onDelete?: () => void
}

export type OutputParserNodeData = {
  label: string
  parser_type: 'json' | 'pydantic' | 'regex' | 'csv' | 'datetime' | 'enum'
  schema_json: string
  strict: boolean
  isSelected?: boolean
  onDelete?: () => void
}

export type RetrieverNodeData = DebugNodeFields & {
  label: string
  search_type: 'similarity' | 'mmr' | 'bm25_hybrid' | 'multi_query' | 'contextual_compression' | 'parent_document' | 'self_query'
  collection_name: string
  top_k: number
  score_threshold: number
  rerank: boolean
  embedding_provider: 'openai' | 'local'
  embedding_model: string
  embedding_api_key: string
  isSelected?: boolean
  onDelete?: () => void
}

export type ConnectionNodeData = {
  label: string
  connection_id: string
  connection_type: 'postgres' | 'mysql' | 'mongodb' | 'redis' | 'snowflake' | 'aws_s3' | 'sqlite' | 'custom_api'
  icon: string
  description: string
  config: Record<string, any>
  status: 'connected' | 'error' | 'untested'
  status_msg?: string
  isSelected?: boolean
  onDelete?: () => void
}

export type KnowledgeBaseNodeData = {
  label: string
  kb_id: string
  icon: string
  description: string
  chunk_count: number
  embedding_provider: string
  embedding_model: string
  top_k: number
  score_threshold: number
  isSelected?: boolean
  onDelete?: () => void
}

export type MiddlewareNodeData = {
  label: string
  middleware_type: 'content_moderation' | 'cost_tracker' | 'rate_limiter' | 'prompt_injection' | 'grounding' | 'custom_rule' | 'custom_pattern'
  config: Record<string, any>
  enabled: boolean
  isSelected?: boolean
  onDelete?: () => void
}

export type SkillNodeData = {
  label: string
  skill_id: string
  skill_version?: number   // pinned version; unset = always the latest
  requiredTools?: string[]  // the library's list of tools it needs, kept in sync by the canvas (the server ignores it)
  icon: string
  description: string
  instructions: string
  tool_ids: string[]
  tags: string[]
  category: string
  isSelected?: boolean
  onDelete?: () => void
}

export type SyntheticDataColumnType =
  | 'string'
  | 'integer'
  | 'number'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'email'
  | 'uuid'
  | 'category'

export type SyntheticDataColumn = {
  id: string
  name: string
  type: SyntheticDataColumnType
  nullable: boolean
  unique: boolean
  min?: number
  max?: number
  values?: string // comma-separated category values
}

export type SyntheticDataNodeData = {
  label: string
  dataset_name: string
  row_count: number
  output_format: 'json' | 'jsonl' | 'csv'
  schema_mode: 'manual' | 'json'
  schema_json: string
  columns: SyntheticDataColumn[]
  locale: string
  seed: number
  strict_schema: boolean
  include_edge_cases: boolean
  strict_routing?: boolean
  prompt_instructions: string
  generated_preview_rows?: Array<Record<string, unknown>>
  generated_preview_model?: string
  generated_preview_at?: string
  isSelected?: boolean
  onDelete?: () => void
}

// ── Agent nodes ───────────────────────────────────────────────────────────────

export type MasterAgentNodeData = {
  label: string
  // Which LLM the master agent uses for planning + delegation decisions
  provider: string
  model: string
  api_key: string
  timeout_ms?: number
  max_retries?: number
  retry_backoff_ms?: number
  fallback_provider?: string
  fallback_model?: string
  fallback_api_key?: string
  fallback_base_url?: string
  base_url?: string
  // The goal / system instruction for the master agent
  goal: string
  // Max steps the master agent can take before stopping
  max_steps: number
  // Coordination strategy
  strategy: 'sequential' | 'parallel' | 'dynamic'
  isSelected?: boolean
  onDelete?: () => void
}

export type ChildAgentNodeData = DebugNodeFields & {
  label: string
  // Which master this child is bound to (node id)
  master_id: string
  // The specialist role this child plays
  role: string
  // Which LLM the child uses (can differ from master)
  provider: string
  model: string
  api_key: string
  timeout_ms?: number
  max_retries?: number
  retry_backoff_ms?: number
  fallback_provider?: string
  fallback_model?: string
  fallback_api_key?: string
  fallback_base_url?: string
  base_url?: string
  // Tools the child is allowed to use (tool node ids from the same flow)
  allowed_tool_ids?: string[]   // absent on imported / generated flows
  // Skills attached to this child
  skill_ids?: string[]
  // System prompt injected for this specialist
  system_prompt: string
  // 'llm' (default) runs a model call; 'external' calls a remote agent over HTTP;
  // 'pipeline' runs a published app as a sub-pipeline
  kind?: 'llm' | 'external' | 'pipeline'
  // Pipeline settings (kind === 'pipeline')
  app_id?: string
  app_name?: string
  app_version?: number
  // External agent settings (kind === 'external')
  endpoint_url?: string
  protocol?: 'openai' | 'rest' | 'a2a'
  auth_type?: 'none' | 'bearer' | 'header'
  auth_header?: string
  request_template?: string
  response_path?: string
  // Skills: loaded on demand (default) or all in the prompt
  skill_mode?: 'on_demand' | 'always'
  // Dropped from a saved agent (utils/savedAgents.ts): which one, at which version
  saved_agent_id?: string
  saved_agent_version?: number
  // Dropped from a built-in agent (backend/agents/, utils/agentCatalog.ts)
  builtin_agent_id?: string
  isSelected?: boolean
  onDelete?: () => void
}

// ── Pipeline control node data types ─────────────────────────────────────────

export type StartNodeData = {
  label: string
  isSelected?: boolean
  onDelete?: () => void
}

export type StopNodeData = {
  label: string
  isSelected?: boolean
  onDelete?: () => void
}

// ── Gateway node ──────────────────────────────────────────────────────────────
// Gateway types:
//   condition   — if/else branch based on a JS expression over the input
//   merge       — wait for all incoming branches, pass through when all arrive
//   split       — fan-out: duplicate output to N parallel branches
//   loop        — repeat N times or until a stop condition is met
export type GatewayKind = 'condition' | 'merge' | 'split' | 'loop'

export type GatewayNodeData = {
  label: string
  kind: GatewayKind
  // condition gateway
  condition_expr?: string      // JS-style expression, e.g. "output.includes('error')"
  true_label?: string          // label on the true/yes edge
  false_label?: string         // label on the false/no edge
  // split gateway
  branch_count?: number        // how many parallel branches to fan out to (2–5)
  // loop gateway
  max_iterations?: number      // hard cap on loop iterations
  loop_condition?: string      // stop condition expression
  isSelected?: boolean
  onDelete?: () => void
}

// ── Graph primitives ──────────────────────────────────────────────────────────

export type FlowNode = Node<
  | LlmNodeData
  | ToolNodeData
  | ToolkitNodeData
  | MemoryNodeData
  | CacheNodeData
  | DocLoaderNodeData
  | TextSplitterNodeData
  | EmbeddingNodeData
  | VectorStoreNodeData
  | RetrieverNodeData
  | RerankerNodeData
  | HumanGateNodeData
  | CheckpointerNodeData
  | WorkflowStepNodeData
  | OutputParserNodeData
  | MasterAgentNodeData
  | ChildAgentNodeData
  | ConnectionNodeData
  | KnowledgeBaseNodeData
  | SkillNodeData
  | SyntheticDataNodeData
  | MiddlewareNodeData
  | StartNodeData
  | StopNodeData
  | GatewayNodeData,
  | 'llm' | 'tool' | 'toolkit' | 'memory' | 'cache'
  | 'doc_loader' | 'text_splitter' | 'embedding' | 'vector_store' | 'retriever'
  | 'reranker' | 'human_gate' | 'checkpointer' | 'wf_step' | 'output_parser'
  | 'master_agent' | 'child_agent' | 'connection' | 'knowledge_base' | 'skill'
  | 'synthetic_data' | 'middleware' | 'start' | 'stop' | 'gateway'
>
export type FlowEdge = Edge
