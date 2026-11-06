/**
 * Sidebar — the left panel of FlowBuilder.
 * All accordion sections: General, LLM, Tools, MCP, Toolkits, Memory, Cache,
 * RAG pipeline (DocLoader, TextSplitter, Embeddings, VectorStore, Retrievers),
 * Agents, Custom Tools, Knowledge Bases, and Connections.
 */
import { useEffect, useRef, useState } from 'react'
import type { DragEvent, ReactNode } from 'react'
import { deleteCustomDocLoader, useDocLoaders } from '../utils/docLoaders'
import type { DocLoaderDef } from '../utils/docLoaders'
import { CustomDocLoaderModal } from './CustomDocLoaderModal'
import { PipelinesSection } from './PipelinesSection'
import { useAgentCatalog } from '../utils/agentCatalog'
import { useSavedAgents } from '../utils/savedAgents'
import { useRecentNodes } from '../utils/recentNodes'
import { NodeIcon } from './NodeIcon'
import { ConnectionIcon } from './ConnectionIcon'
import { Pencil, Trash2 } from 'lucide-react'
import type {
  ProviderOption,
  ToolCategory,
  ToolCatalogItem,
  KnowledgeBaseRecord,
  ConnectionRecord,
  SkillRecord,
} from '../types'
import type { CustomMcpRecord } from '../types'
import { LIVE_VECTOR_STORES } from '../types'
import type { CustomToolRecord } from './CustomToolModal'

interface Props {
  // Collapse to an icon rail
  collapsed: boolean
  onToggleCollapsed: () => void

  // Catalog data
  providers: ProviderOption[]
  toolCategories: ToolCategory[]
  /** Why the built-in tool catalog didn't load, if it didn't */
  toolsError?: string | null
  onRetryTools?: () => void
  /** Open Settings → Tools & MCP packages, where tools and MCP servers not in the sidebar are installed */
  onManagePackages?: () => void
  /** Open Settings → Agents, where built-in agents not in the sidebar are installed */
  onManageAgents?: () => void
  customTools: CustomToolRecord[]
  customMcpServers: CustomMcpRecord[]
  connections: ConnectionRecord[]
  knowledgeBases: KnowledgeBaseRecord[]
  skills: SkillRecord[]

  // Section open state
  isGeneralSectionOpen: boolean; setIsGeneralSectionOpen: (v: boolean) => void
  isLlmSectionOpen: boolean; setIsLlmSectionOpen: (v: boolean) => void
  isToolsSectionOpen: boolean; setIsToolsSectionOpen: (v: boolean) => void
  isMcpSectionOpen: boolean; setIsMcpSectionOpen: (v: boolean) => void
  isToolkitSectionOpen: boolean; setIsToolkitSectionOpen: (v: boolean) => void
  isMemorySectionOpen: boolean; setIsMemorySectionOpen: (v: boolean) => void
  isCacheSectionOpen: boolean; setIsCacheSectionOpen: (v: boolean) => void
  isDocLoaderSectionOpen: boolean; setIsDocLoaderSectionOpen: (v: boolean) => void
  isTextSplitterSectionOpen: boolean; setIsTextSplitterSectionOpen: (v: boolean) => void
  isEmbeddingSectionOpen: boolean; setIsEmbeddingSectionOpen: (v: boolean) => void
  isVectorStoreSectionOpen: boolean; setIsVectorStoreSectionOpen: (v: boolean) => void
  isRetrieverSectionOpen: boolean; setIsRetrieverSectionOpen: (v: boolean) => void
  isAgentsSectionOpen: boolean; setIsAgentsSectionOpen: (v: boolean) => void
  isCustomToolsSectionOpen: boolean; setIsCustomToolsSectionOpen: (v: boolean) => void
  isConnectionsSectionOpen: boolean; setIsConnectionsSectionOpen: (v: boolean) => void
  isKnowledgeBaseSectionOpen: boolean; setIsKnowledgeBaseSectionOpen: (v: boolean) => void
  isPipelinesSectionOpen: boolean; setIsPipelinesSectionOpen: (v: boolean) => void
  isSkillsSectionOpen: boolean; setIsSkillsSectionOpen: (v: boolean) => void
  isFrameworksSectionOpen: boolean; setIsFrameworksSectionOpen: (v: boolean) => void
  isSyntheticDataSectionOpen: boolean; setIsSyntheticDataSectionOpen: (v: boolean) => void
  isRerankerSectionOpen: boolean; setIsRerankerSectionOpen: (v: boolean) => void
  isHumanGateSectionOpen: boolean; setIsHumanGateSectionOpen: (v: boolean) => void
  isCheckpointerSectionOpen: boolean; setIsCheckpointerSectionOpen: (v: boolean) => void
  isWorkflowSectionOpen: boolean; setIsWorkflowSectionOpen: (v: boolean) => void
  isOutputParserSectionOpen: boolean; setIsOutputParserSectionOpen: (v: boolean) => void
  isMiddlewareSectionOpen: boolean; setIsMiddlewareSectionOpen: (v: boolean) => void

  // Search / filter
  collapsedProviders: Record<string, boolean>
  toggleProviderGroup: (id: string) => void
  searchModelQuery: string; setSearchModelQuery: (v: string) => void
  searchToolQuery: string; setSearchToolQuery: (v: string) => void
  searchMcpQuery: string; setSearchMcpQuery: (v: string) => void

  // Drag handlers
  onDragStartLlm: (e: DragEvent<HTMLDivElement>, providerId: string, model: string) => void
  onDragStartTool: (e: DragEvent<HTMLDivElement>, tool: ToolCatalogItem) => void
  onDragStartToolkit: (e: DragEvent<HTMLDivElement>) => void

  // Modal openers
  onOpenCustomToolModal: () => void
  onEditCustomTool: (ct: CustomToolRecord) => void
  onDeleteCustomTool: (ct: CustomToolRecord) => void
  onOpenCustomMcpModal: () => void
  onEditCustomMcp: (s: CustomMcpRecord) => void
  onDeleteCustomMcp: (s: CustomMcpRecord) => void
  onOpenConnectionModal: () => void
  onEditConnection: (c: ConnectionRecord) => void
  onDeleteConnection: (c: ConnectionRecord) => void
  onOpenKnowledgeBaseModal: () => void
  onDeleteKnowledgeBase: (kb: KnowledgeBaseRecord) => void
  onOpenSkillsModal: () => void
  onDeleteSkill: (skill: SkillRecord) => void
  fetchCustomMcpServers: () => void
  fetchConnections: () => void
  fetchKnowledgeBases: () => void
  fetchSkills: () => void
  fetchCustomTools: () => void
}

const PROVIDER_ICONS: Record<string, string> = {
  openai: '◎',
  anthropic: '✶',
  groq: '⚡',
  gemini: '✦',
  mistral: '🌀',
  together: '⛓',
  huggingface: '🤗',
  fireworks:   '🎆',
  deepseek:    '🔮',
  xai:         '𝕏',
  cerebras:    '⚙️',
  perplexity:  '🔭',
  ollama: '🦙',
  llamacpp: '🦙',
  jan: '👋',
  azure: '☁',
  bedrock: '🪨',
  typesafe: '🛡',
  mock: '◌',
}

function getProviderIcon(providerId: string): string {
  return PROVIDER_ICONS[providerId] ?? '◌'
}

interface PresetLike { desc: string; label?: string; role?: string; category?: string }

const MEMORY_PRESETS = [
  { strategy: 'sliding_window' as const, label: 'Sliding Win', icon: '🪟', desc: 'Keeps recent turns within token budget, drops oldest first.', token_budget: 4096 },
  { strategy: 'summarize' as const, label: 'Summarize', icon: '📝', desc: 'Retains system prompt + last 4 turns. Compress older context.', token_budget: 3000 },
  { strategy: 'last_k' as const, label: 'Last K Turns', icon: '🔢', desc: 'Keeps last 8 messages regardless of token count.', token_budget: 8192 },
  { strategy: 'vector' as const, label: 'Vector Mem', icon: '🧲', desc: 'Store conversation chunks in a vector DB for long-term semantic recall.', token_budget: 8192 },
  { strategy: 'knowledge_graph' as const, label: 'KG Memory', icon: '🕸️', desc: 'Build a knowledge graph from conversations using mem0 or Zep.', token_budget: 8192 },
]

const CACHE_PRESETS = [
  { scope: 'prompt' as const, label: 'Prompt Cache', icon: '💬', desc: 'Cache by prompt text. Same question always hits, regardless of model.', ttl_seconds: 3600, max_size: 500 },
  { scope: 'model' as const, label: 'Model Cache', icon: '🤖', desc: 'Cache by prompt + model. Different models generate separate entries.', ttl_seconds: 1800, max_size: 1000 },
  { scope: 'strict' as const, label: 'Strict Cache', icon: '🔒', desc: 'Cache by prompt + model + temperature + top_p + max_tokens.', ttl_seconds: 7200, max_size: 200 },
]

const TEXT_SPLITTER_PRESETS = [
  { splitter_type: 'recursive_character' as const, label: 'Recursive',  icon: '✂️', desc: 'Smart split on newlines, spaces, etc. Best general-purpose choice.' },
  { splitter_type: 'token' as const,               label: 'Token Split', icon: '🔢', desc: 'Split by token count using tiktoken. Ideal for LLM context windows.' },
  { splitter_type: 'markdown' as const,            label: 'Markdown',    icon: '📑', desc: 'Respects headers, code fences, and lists when splitting.' },
  { splitter_type: 'semantic' as const,            label: 'Semantic',    icon: '🧠', desc: 'Splits on embedding similarity boundaries. Best context preservation.' },
  { splitter_type: 'sentence' as const,            label: 'Sentence',    icon: '💬', desc: 'Splits on sentence boundaries using spaCy or NLTK.' },
  { splitter_type: 'html' as const,                label: 'HTML',        icon: '🏷️', desc: 'Respects HTML tags and structure when splitting web pages.' },
]

const EMBEDDING_PRESETS = [
  { provider: 'openai'       as const, model: 'text-embedding-3-small',                          label: 'OpenAI Embed',  icon: '🤖', desc: 'text-embedding-3-small/large. Best accuracy, requires API key.' },
  { provider: 'local'        as const, model: 'sentence-transformers/all-MiniLM-L6-v2',          label: 'Local MiniLM',  icon: '💻', desc: 'sentence-transformers via HuggingFace. Runs fully offline.' },
  { provider: 'cohere'       as const, model: 'embed-english-v3.0',                              label: 'Cohere Embed',  icon: '🟠', desc: 'embed-english-v3.0 / multilingual-v3.0. Excellent retrieval.' },
  { provider: 'google'       as const, model: 'text-embedding-004',                              label: 'Google Embed',  icon: '🌈', desc: 'text-embedding-004 (Gemini). Best Google Cloud integration.' },
  { provider: 'azure_openai' as const, model: 'text-embedding-3-small',                          label: 'Azure OpenAI',  icon: '🔵', desc: 'OpenAI models deployed on Azure. Enterprise / compliance.' },
  { provider: 'mistral'      as const, model: 'mistral-embed',                                   label: 'Mistral Embed', icon: '🌊', desc: 'mistral-embed. Efficient multilingual embedding model.' },
  { provider: 'ollama'       as const, model: 'nomic-embed-text',                                label: 'Ollama Embed',  icon: '🦙', desc: 'Local Ollama models — nomic-embed-text, mxbai-embed-large.' },
  { provider: 'llamacpp'     as const, model: 'default',                                         label: 'llama.cpp Embed', icon: '🦙', desc: 'Local llama-server started with --embeddings (any GGUF embedding model).' },
  { provider: 'bedrock'      as const, model: 'amazon.titan-embed-text-v2:0',                    label: 'Bedrock Embed', icon: '☁️', desc: 'AWS Bedrock — Titan v2 or Cohere on Bedrock.' },
  { provider: 'voyage'       as const, model: 'voyage-3',                                        label: 'Voyage AI',     icon: '🚀', desc: 'voyage-3 / voyage-code-3. State-of-the-art retrieval models.' },
  { provider: 'nomic'        as const, model: 'nomic-embed-text-v1.5',                           label: 'Nomic Embed',   icon: '🗺️', desc: 'nomic-embed-text-v1.5. Open, Matryoshka-compatible.' },
  { provider: 'anthropic'    as const, model: 'voyage-3',                                        label: 'Anthropic Emb', icon: '🤝', desc: 'Anthropic embeddings via Voyage AI integration.' },
]

const VECTOR_STORE_PRESETS = [
  { store_type: 'local' as const, label: 'Local', icon: '💾', desc: 'Built-in store in the app database. Zero setup; good up to a few thousand chunks.' },
  { store_type: 'pgvector' as const, label: 'pgvector', icon: '🐘', desc: 'Production-grade. Stores vectors in Postgres using the pgvector extension, with an HNSW index.' },
  { store_type: 'chroma' as const, label: 'Chroma DB', icon: '🌈', desc: 'Zero-dependency local vector store. Persists to disk. Great for dev.' },
  { store_type: 'pinecone' as const, label: 'Pinecone', icon: '🌲', desc: 'Fully managed cloud vector database. Best for scale.' },
  { store_type: 'weaviate' as const, label: 'Weaviate', icon: '🔷', desc: 'Cloud-native vector database with hybrid search support.' },
  { store_type: 'qdrant' as const, label: 'Qdrant', icon: '⚡', desc: 'High-performance vector search. Cloud or self-hosted.' },
  { store_type: 'milvus' as const, label: 'Milvus', icon: '🏛️', desc: 'Open-source, built for billion-scale similarity search.' },
  { store_type: 'elasticsearch' as const, label: 'Elastic', icon: '🔍', desc: 'Full-text + dense vector hybrid search with Elasticsearch.' },
  { store_type: 'mongodb_atlas' as const, label: 'MongoDB Atlas', icon: '🍃', desc: 'Atlas Vector Search — fully managed on MongoDB Atlas.' },
  { store_type: 'opensearch' as const, label: 'OpenSearch', icon: '☁️', desc: 'AWS OpenSearch k-NN plugin. Native AWS IAM auth.' },
  { store_type: 'redis' as const, label: 'Redis', icon: '🔴', desc: 'Sub-millisecond in-memory vector search via RedisVL / Redis Stack.' },
  { store_type: 'faiss' as const, label: 'FAISS', icon: '🧮', desc: 'Meta FAISS — fastest local CPU/GPU similarity search, no server.' },
  { store_type: 'azure_ai_search' as const, label: 'Azure Search', icon: '🔵', desc: 'Azure AI Search — managed, native Azure OpenAI integration.' },
  { store_type: 'vertex_ai' as const, label: 'Vertex AI', icon: '🌐', desc: 'Google Cloud Vertex AI Vector Search (Matching Engine).' },
  { store_type: 'lancedb' as const, label: 'LanceDB', icon: '🏹', desc: 'Serverless embedded store — local disk, S3, or GCS backed.' },
]

const RETRIEVER_PRESETS = [
  { search_type: 'similarity' as const,              label: 'Similarity',   icon: '🎯', desc: 'Standard cosine top-k. Best general-purpose choice for RAG.' },
  { search_type: 'mmr' as const,                     label: 'MMR Search',   icon: '🔀', desc: 'Balances relevance with diversity. Avoids returning near-duplicate chunks.' },
  { search_type: 'bm25_hybrid' as const,             label: 'BM25 Hybrid',  icon: '⚖️', desc: 'Combines dense vector + keyword (BM25) scoring. Best recall on keyword-heavy queries.' },
  { search_type: 'multi_query' as const,             label: 'Multi-Query',  icon: '🔁', desc: 'Generates multiple query variants; unions the results for better recall.' },
  { search_type: 'contextual_compression' as const,  label: 'Compress',     icon: '🗜️', desc: 'Filters and compresses retrieved chunks to only the relevant spans.' },
  { search_type: 'parent_document' as const,         label: 'Parent Doc',   icon: '📄', desc: 'Retrieves small child chunks but returns their full parent document.' },
  { search_type: 'self_query' as const,              label: 'Self-Query',   icon: '🔮', desc: 'LLM auto-generates metadata filters from natural language queries.' },
]

const RERANKER_PRESETS = [
  { reranker_type: 'cohere' as const,        label: 'Cohere',        icon: '🟠', desc: 'Cohere Rerank API — state-of-the-art managed reranker.', model: 'rerank-english-v3.0', top_n: 5 },
  { reranker_type: 'cross_encoder' as const, label: 'CrossEncoder',  icon: '🤗', desc: 'HuggingFace cross-encoder. Runs locally, no API key needed.', model: 'cross-encoder/ms-marco-MiniLM-L-6-v2', top_n: 5 },
  { reranker_type: 'flashrank' as const,     label: 'FlashRank',     icon: '⚡', desc: 'Ultra-fast local reranker optimised for latency.', model: 'ms-marco-MiniLM-L-12-v2', top_n: 5 },
  { reranker_type: 'bge' as const,           label: 'BGE Reranker',  icon: '🔵', desc: 'BAAI/bge-reranker-v2-m3. Best open-source multilingual reranker.', model: 'BAAI/bge-reranker-v2-m3', top_n: 5 },
]

// Guardrails (node type `middleware`), shown in three groups
const MIDDLEWARE_GROUPS = ['Accuracy', 'Safety', 'Limits'] as const
const MIDDLEWARE_PRESETS = [
  { mw_type: 'grounding'          as const, group: 'Accuracy', label: 'Grounding',   icon: '📌', desc: 'Grounding check — blocks made-up answers (hallucinations) not backed by tool output or documents.' },
  { mw_type: 'custom_rule'        as const, group: 'Accuracy', label: 'Custom Rule', icon: '📝', desc: 'Your own rule in plain English, checked by a model after every answer.' },
  { mw_type: 'content_moderation' as const, group: 'Safety',   label: 'Moderation',  icon: '🔍', desc: 'Block harmful content, detect PII, enforce keyword blocklist.' },
  { mw_type: 'prompt_injection'   as const, group: 'Safety',   label: 'Inj. Guard',  icon: '🧬', desc: 'Detect prompt injection, jailbreaks & instruction overrides.' },
  { mw_type: 'custom_pattern'     as const, group: 'Safety',   label: 'Custom Pattern', icon: '🔤', desc: 'Your own words or regex patterns, checked on the prompt, the answer or both.' },
  { mw_type: 'cost_tracker'       as const, group: 'Limits',   label: 'Cost Cap',    icon: '💰', desc: 'Hard token + USD budget per run. Blocks if exceeded.' },
  { mw_type: 'rate_limiter'       as const, group: 'Limits',   label: 'Rate Limit',  icon: '🚦', desc: 'Requests-per-minute sliding window per session, caller or app.' },
]

const HUMAN_GATE_PRESETS = [
  { gate_type: 'approval' as const, label: 'Approval',  icon: '✅', desc: 'Pause pipeline — human must approve before continuing.', timeout_hours: 24 },
  { gate_type: 'edit' as const,     label: 'Edit Gate',  icon: '✏️', desc: 'Pause and let a human edit the agent output before passing it forward.', timeout_hours: 24 },
  { gate_type: 'review' as const,   label: 'Review',    icon: '🔎', desc: 'Non-blocking review — human can flag issues without stopping the pipeline.', timeout_hours: 48 },
]

const CHECKPOINTER_PRESETS = [
  { mode: 'resume' as const,  label: 'Resume',     icon: '💾', desc: 'Save each finished step; resuming a cut-off or failed run continues after the last one.' },
  { mode: 'restart' as const, label: 'Start Over', icon: '🔁', desc: 'Save each step for inspection, but resuming runs everything again — for tools whose results go stale.' },
  { mode: 'off' as const,     label: 'No Data',    icon: '🚫', desc: 'Keep no model or tool output, only the run\'s status. Resuming starts over.' },
]

const WORKFLOW_STEP_PRESETS = [
  { step_type: 'ask' as const,       label: 'Ask User',  icon: '💬', desc: 'Ask a question (e.g. "Which city?") and pause until the user replies.' },
  { step_type: 'choice' as const,    label: 'Choice',    icon: '📋', desc: 'Show a list of options (e.g. search results) and pause until the user picks one.' },
  { step_type: 'confirm' as const,   label: 'Confirm',   icon: '☑️', desc: 'Yes / no confirmation before continuing (e.g. before booking).' },
  { step_type: 'tool_call' as const, label: 'Tool Call', icon: '🔌', desc: 'Call a tool or MCP automatically and save the result in a variable.' },
  { step_type: 'message' as const,   label: 'Message',   icon: '📢', desc: 'Show a message to the user and continue without waiting.' },
]

const OUTPUT_PARSER_PRESETS = [
  { parser_type: 'json' as const,     label: 'JSON',     icon: '{ }', desc: 'Parse LLM output as JSON. Retries on invalid JSON automatically.' },
  { parser_type: 'pydantic' as const, label: 'Pydantic',  icon: '🐍', desc: 'Validate and coerce output into a typed Pydantic model schema.' },
  { parser_type: 'regex' as const,    label: 'Regex',    icon: '🔍', desc: 'Extract structured data using a named-group regular expression.' },
  { parser_type: 'csv' as const,      label: 'CSV',      icon: '📊', desc: 'Parse comma-separated values output into rows.' },
  { parser_type: 'datetime' as const, label: 'DateTime', icon: '📅', desc: 'Parse natural language dates into ISO-8601 datetime strings.' },
  { parser_type: 'enum' as const,     label: 'Enum',     icon: '🔘', desc: 'Force output to one of a predefined set of allowed values.' },
]

const SYNTHETIC_DATA_PRESETS = [
  {
    id: 'synth-schema',
    label: 'Schema Planner',
    icon: '🧩',
    category: 'Core',
    desc: 'Plans a realistic schema (columns, types, constraints) from requirements.',
  },
  {
    id: 'synth-generate',
    label: 'Data Generator',
    icon: '🧪',
    category: 'Core',
    desc: 'Generates synthetic records that follow the schema and edge-case coverage goals.',
  },
  {
    id: 'synth-validate',
    label: 'Quality Validator',
    icon: '✅',
    category: 'Core',
    desc: 'Checks synthetic output for schema compliance, balance, and anomaly issues.',
  },
  {
    id: 'synth-salesforce',
    label: 'Salesforce Data',
    icon: '☁️',
    category: 'Business Systems',
    desc: 'Generates CRM-like Account, Contact, Lead and Opportunity style records.',
  },
  {
    id: 'synth-pii',
    label: 'PII Data',
    icon: '🪪',
    category: 'Security & Privacy',
    desc: 'Generates realistic personal-identifiable records for masking and privacy testing.',
  },
  {
    id: 'synth-orders',
    label: 'Orders Data',
    icon: '📦',
    category: 'Business Systems',
    desc: 'Generates ecommerce orders, line items, fulfillment and payment fields.',
  },
  {
    id: 'synth-sales',
    label: 'Sales Data',
    icon: '💰',
    category: 'Business Systems',
    desc: 'Generates transactional sales metrics for dashboards and forecasting tests.',
  },
  {
    id: 'synth-hr',
    label: 'HR Data',
    icon: '🧑‍💼',
    category: 'Business Systems',
    desc: 'Generates employee lifecycle data: hiring, role, compensation and performance.',
  },
  {
    id: 'synth-graphdb',
    label: 'GraphDB Data',
    icon: '🕸️',
    category: 'Graph & Network',
    desc: 'Generates node/edge style entity relationship data for graph workloads.',
  },
  {
    id: 'synth-finance',
    label: 'Finance Data',
    icon: '🏦',
    category: 'Industry',
    desc: 'Generates ledger, balance, payment, and account-level finance records.',
  },
  {
    id: 'synth-healthcare',
    label: 'Healthcare Data',
    icon: '🏥',
    category: 'Industry',
    desc: 'Generates patient, visit, diagnosis, and treatment style datasets.',
  },
  {
    id: 'synth-marketing',
    label: 'Marketing Data',
    icon: '📣',
    category: 'Business Systems',
    desc: 'Generates campaign, channel, attribution and conversion event records.',
  },
  {
    id: 'synth-support',
    label: 'Support Tickets',
    icon: '🎫',
    category: 'Business Systems',
    desc: 'Generates helpdesk tickets, priorities, SLAs and resolution outcomes.',
  },
  {
    id: 'synth-supply-chain',
    label: 'Supply Chain',
    icon: '🚚',
    category: 'Industry',
    desc: 'Generates inventory, shipments, vendors and warehouse movement data.',
  },
  {
    id: 'synth-iot',
    label: 'IoT Telemetry',
    icon: '📡',
    category: 'Machine Data',
    desc: 'Generates time-series sensor telemetry and device state change records.',
  },
  {
    id: 'synth-fraud',
    label: 'Fraud Detection',
    icon: '🕵️',
    category: 'Security & Privacy',
    desc: 'Generates risk signals and suspicious transaction patterns for model testing.',
  },
  {
    id: 'synth-log-events',
    label: 'Log Events',
    icon: '🧾',
    category: 'Machine Data',
    desc: 'Generates structured application logs and observability event streams.',
  },
  {
    id: 'synth-retail',
    label: 'Retail POS',
    icon: '🛒',
    category: 'Retail & Commerce',
    desc: 'Generates point-of-sale transactions, baskets, discounts and payment mixes.',
  },
  {
    id: 'synth-public-sector',
    label: 'Public Services',
    icon: '🏛️',
    category: 'Public Services',
    desc: 'Generates public-sector case records, request types, and SLA completion metrics.',
  },
  {
    id: 'synth-qa-testing',
    label: 'QA Test Fixtures',
    icon: '🧪',
    category: 'Dev & QA',
    desc: 'Generates deterministic fixtures with boundary, invalid, and missing-field cases.',
  },
  {
    id: 'synth-csv-upload',
    label: 'CSV Sample Upload',
    icon: '📤',
    category: 'Data Onboarding',
    desc: 'Upload an existing CSV sample to infer schema and seed synthetic generation.',
  },
]

type GroupId = 'essentials' | 'tools' | 'knowledge' | 'control'

const GROUPS: { id: GroupId; label: string; icon: string }[] = [
  { id: 'essentials', label: 'Essentials', icon: 'llm' },
  { id: 'tools', label: 'Tools & integrations', icon: 'tool' },
  { id: 'knowledge', label: 'Knowledge (RAG)', icon: 'knowledge_base' },
  { id: 'control', label: 'Control & safety', icon: 'middleware' },
]

// Essentials and tools start open; the RAG and control groups stay folded until needed.
const DEFAULT_GROUPS_OPEN: Record<GroupId, boolean> = { essentials: true, tools: true, knowledge: false, control: false }
const GROUPS_STORAGE_KEY = 'univ.sidebarGroups.v1'

function readGroupsOpen(): Record<GroupId, boolean> {
  try {
    return { ...DEFAULT_GROUPS_OPEN, ...JSON.parse(localStorage.getItem(GROUPS_STORAGE_KEY) ?? '{}') }
  } catch {
    return DEFAULT_GROUPS_OPEN
  }
}

interface SidebarGroupProps {
  id: GroupId
  label: string
  visible: boolean
  isOpen: boolean
  onToggle: () => void
  children: ReactNode
}

function CatalogError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="catalog-error" role="alert">
      <span>{message}</span>
      {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
    </div>
  )
}

function SidebarGroup({ id, label, visible, isOpen, onToggle, children }: SidebarGroupProps) {
  if (!visible) return null
  return (
    <section className={`sidebar-group${isOpen ? ' sidebar-group--open' : ''}`} aria-labelledby={`sidebar-group-${id}`}>
      <button type="button" id={`sidebar-group-${id}`} className="sidebar-group-header" aria-expanded={isOpen} onClick={onToggle}>
        <span>{label}</span>
        <span className="sidebar-group-chevron" aria-hidden="true">›</span>
      </button>
      {isOpen && <div className="sidebar-group-body">{children}</div>}
    </section>
  )
}

export function Sidebar({
  collapsed, onToggleCollapsed,
  providers, toolCategories, toolsError, onRetryTools, onManagePackages, onManageAgents, customTools, customMcpServers, connections, knowledgeBases, skills,
  isGeneralSectionOpen, setIsGeneralSectionOpen,
  isLlmSectionOpen, setIsLlmSectionOpen,
  isToolsSectionOpen, setIsToolsSectionOpen,
  isMcpSectionOpen, setIsMcpSectionOpen,
  isToolkitSectionOpen, setIsToolkitSectionOpen,
  isMemorySectionOpen, setIsMemorySectionOpen,
  isCacheSectionOpen, setIsCacheSectionOpen,
  isDocLoaderSectionOpen, setIsDocLoaderSectionOpen,
  isTextSplitterSectionOpen, setIsTextSplitterSectionOpen,
  isEmbeddingSectionOpen, setIsEmbeddingSectionOpen,
  isVectorStoreSectionOpen, setIsVectorStoreSectionOpen,
  isRetrieverSectionOpen, setIsRetrieverSectionOpen,
  isAgentsSectionOpen, setIsAgentsSectionOpen,
  isConnectionsSectionOpen, setIsConnectionsSectionOpen,
  isKnowledgeBaseSectionOpen, setIsKnowledgeBaseSectionOpen,
  isPipelinesSectionOpen, setIsPipelinesSectionOpen,
  isSkillsSectionOpen, setIsSkillsSectionOpen,
  isFrameworksSectionOpen, setIsFrameworksSectionOpen,
  isSyntheticDataSectionOpen, setIsSyntheticDataSectionOpen,
  isRerankerSectionOpen, setIsRerankerSectionOpen,
  isHumanGateSectionOpen, setIsHumanGateSectionOpen,
  isCheckpointerSectionOpen, setIsCheckpointerSectionOpen,
  isWorkflowSectionOpen, setIsWorkflowSectionOpen,
  isOutputParserSectionOpen, setIsOutputParserSectionOpen,
  isMiddlewareSectionOpen, setIsMiddlewareSectionOpen,
  collapsedProviders, toggleProviderGroup,
  searchModelQuery, setSearchModelQuery,
  searchToolQuery, setSearchToolQuery,
  searchMcpQuery, setSearchMcpQuery,
  isCustomToolsSectionOpen: _isCustomToolsSectionOpen, setIsCustomToolsSectionOpen: _setIsCustomToolsSectionOpen,
  onDragStartLlm, onDragStartTool, onDragStartToolkit,
  onOpenCustomToolModal, onEditCustomTool, onDeleteCustomTool,
  onOpenCustomMcpModal, onEditCustomMcp, onDeleteCustomMcp,
  onOpenConnectionModal, onEditConnection, onDeleteConnection,
  onOpenKnowledgeBaseModal, onDeleteKnowledgeBase,
  onOpenSkillsModal, onDeleteSkill: _onDeleteSkill,
  fetchCustomMcpServers, fetchConnections, fetchKnowledgeBases, fetchSkills: _fetchSkills,
}: Props) {
  const allDocLoaders = useDocLoaders()
  const recentNodes = useRecentNodes()
  const [searchLoaderQuery, setSearchLoaderQuery] = useState('')
  const [docLoaderModal, setDocLoaderModal] = useState<{ open: boolean; loader?: DocLoaderDef }>({ open: false })
  const loaderQuery = searchLoaderQuery.trim().toLowerCase()
  const matchesLoader = (d: DocLoaderDef) =>
    !loaderQuery || d.label.toLowerCase().includes(loaderQuery) || d.desc.toLowerCase().includes(loaderQuery) || d.type.includes(loaderQuery)
    || (d.category ?? '').toLowerCase().includes(loaderQuery)
  // Built-in tools only — frameworks are 'tool'-typed too but have their own section
  // Only installed packages are offered (Settings → Tools & MCP packages); the rest are counted for the browse link
  const allToolItems = toolCategories.filter((c) => c.id === 'agentic_tools').flatMap((c) => c.tools)
  const allMcpItems = toolCategories.flatMap((c) => c.tools.filter((t) => t.type === 'mcp'))
  const toolOnlyItems = allToolItems.filter((t) => t.installed !== false)
  const mcpItems = allMcpItems.filter((t) => t.installed !== false)
  const moreTools = allToolItems.length - toolOnlyItems.length
  const moreMcp = allMcpItems.length - mcpItems.length

  // ── Global search: filters every section; sections with no hits are hidden, hit sections auto-expand ──
  const [globalQuery, setGlobalQuery] = useState('')
  const q = globalQuery.trim().toLowerCase()
  const has = (...fields: (string | undefined)[]) => fields.some((f) => f?.toLowerCase().includes(q))
  /** Per-section search box match (existing behaviour), kept alongside the global search. */
  const has0 = (query: string, ...fields: (string | undefined)[]) =>
    fields.some((f) => f?.toLowerCase().includes(query.toLowerCase()))
  const sec = (...names: string[]) => names.some((n) => n.includes(q))
  const open = (v: boolean) => (q ? true : v)
  const isRecentlyAdded = (createdAt?: string, days = 14): boolean => {
    if (!createdAt) return false
    const raw = createdAt.trim()
    const normalized = /z$|[+-]\d{2}:\d{2}$/i.test(raw) ? raw : `${raw}Z`
    const ts = Date.parse(normalized)
    if (!Number.isFinite(ts)) return false
    return Date.now() - ts <= days * 24 * 60 * 60 * 1000
  }
  /** Keep every preset when the section name matches, otherwise only presets matching label/role/description. */
  const pick = <T extends PresetLike>(items: T[], section: string): T[] =>
    !q || sec(section) ? items : items.filter((i) => has(i.label, i.role, i.desc, i.category))

  const memoryItems = pick(MEMORY_PRESETS, 'memory')
  const cacheItems = pick(CACHE_PRESETS, 'cache')
  const splitterItems = pick(TEXT_SPLITTER_PRESETS, 'text splitters')
  const embeddingItems = pick(EMBEDDING_PRESETS, 'embeddings')
  const vectorStoreItems = pick(VECTOR_STORE_PRESETS, 'vector stores')
  const retrieverItems = pick(RETRIEVER_PRESETS, 'retrievers')
  const rerankerItems = pick(RERANKER_PRESETS, 'rerankers')
  const middlewareItems = pick(MIDDLEWARE_PRESETS, 'guardrails middleware')
  const humanGateItems = pick(HUMAN_GATE_PRESETS, 'human-in-the-loop')
  const checkpointerItems = pick(CHECKPOINTER_PRESETS, 'checkpointing checkpointer resume')
  const workflowItems = pick(WORKFLOW_STEP_PRESETS, 'workflow')
  const outputParserItems = pick(OUTPUT_PARSER_PRESETS, 'output parsers')
  const syntheticDataItems = pick(SYNTHETIC_DATA_PRESETS, 'synthetic data generator dataset')
  const syntheticGroups: { name: string; presets: typeof syntheticDataItems }[] = []
  for (const preset of syntheticDataItems) {
    const name = preset.category || 'Other'
    const group = syntheticGroups.find((g) => g.name === name)
    if (group) group.presets.push(preset)
    else syntheticGroups.push({ name, presets: [preset] })
  }
  const agentCatalog = useAgentCatalog()
  const agentItems = pick(agentCatalog.agents.filter((a) => a.installed)
    .map((a) => ({ ...a, desc: a.description, label: a.name })), 'agents')
  const moreAgents = agentCatalog.agents.filter((a) => !a.installed).length
  const savedAgents = useSavedAgents().filter((a) => !q || sec('agents', 'saved agents') || has(a.name, a.description))

  const llmMatch = (p: ProviderOption, m: string) =>
    (!searchModelQuery || m.toLowerCase().includes(searchModelQuery.toLowerCase())) &&
    (!q || sec('llm providers', 'models') || has(m, p.name, p.id))
  const toolMatch = (t: { name: string; description: string; category?: string }) =>
    (!searchToolQuery || has0(searchToolQuery, t.name, t.description, t.category)) &&
    (!q || sec('tools') || has(t.name, t.description, t.category))
  const mcpMatch = (t: { name: string; description: string; command?: string; category?: string }) =>
    (!searchMcpQuery || has0(searchMcpQuery, t.name, t.description, t.command, t.category)) &&
    (!q || sec('mcp servers', 'servers') || has(t.name, t.description, t.command, t.category))
  // Catalog items grouped by category, in catalog order; custom items get their own group last
  const groupByCategory = (items: ToolCatalogItem[]) => {
    const groups: { name: string; tools: ToolCatalogItem[] }[] = []
    for (const item of items) {
      const name = item.category || 'Other'
      const group = groups.find((g) => g.name === name)
      if (group) group.tools.push(item)
      else groups.push({ name, tools: [item] })
    }
    return groups
  }
  const toolGroups = groupByCategory(toolOnlyItems.filter(toolMatch))
  const visibleCustomTools = customTools.filter(toolMatch)
  const mcpGroups = groupByCategory(mcpItems.filter(mcpMatch))
  const visibleCustomMcp = customMcpServers.filter(mcpMatch)
  // Groups start collapsed; a search expands every group with hits. Keys are "<section>:<group>".
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set())
  const toggleExpanded = (key: string) => setExpandedGroups((prev) => {
    const next = new Set(prev)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })
  const toolGroupOpen = (name: string) => !!searchToolQuery || !!q || expandedGroups.has(`tools:${name}`)
  const toggleToolGroup = (name: string) => toggleExpanded(`tools:${name}`)
  // Agent groups start open (the list is short), so the set records the ones folded shut
  const agentGroupOpen = (name: string) => !!q || !expandedGroups.has(`agents-closed:${name}`)
  const toggleAgentGroup = (name: string) => toggleExpanded(`agents-closed:${name}`)
  // MCP groups start open so built-ins are visible without extra clicks; this set tracks folded groups.
  const mcpGroupOpen = (name: string) => !!searchMcpQuery || !!q || !expandedGroups.has(`mcp-closed:${name}`)
  const toggleMcpGroup = (name: string) => toggleExpanded(`mcp-closed:${name}`)
  const syntheticGroupOpen = (name: string) => !!q || !expandedGroups.has(`synthetic-closed:${name}`)
  const toggleSyntheticGroup = (name: string) => toggleExpanded(`synthetic-closed:${name}`)
  const loaderMatch = (d: DocLoaderDef) => matchesLoader(d) && (!q || sec('document loaders') || has(d.label, d.desc, d.type, d.category))
  // Document loaders by category (catalog order), custom ones first; `ready` counts runnable ones
  const loaderGroups: { name: string; loaders: DocLoaderDef[]; ready: number }[] = []
  for (const d of allDocLoaders.filter(loaderMatch)) {
    const name = d.custom ? 'Custom' : (d.category || 'Other')
    let group = loaderGroups.find((g) => g.name === name)
    if (!group) loaderGroups.push(group = { name, loaders: [], ready: 0 })
    group.loaders.push(d)
    if (d.custom || d.available !== false) group.ready += 1
  }
  const loaderGroupOpen = (name: string) => !!searchLoaderQuery || !!q || expandedGroups.has(`loaders:${name}`)
  const toggleLoaderGroup = (name: string) => toggleExpanded(`loaders:${name}`)
  const frameworkTools = toolCategories.filter((c) => c.id === 'frameworks').flatMap((c) => c.tools)
    .filter((t) => !q || sec('frameworks') || has(t.name, t.description))
  const kbItems = knowledgeBases.filter((kb) => !q || sec('knowledge base') || has(kb.name, kb.description))
  const connItems = connections.filter((c) => !q || sec('connections') || has(c.name, c.type, c.description))
  const skillItems = skills.filter((s) => !q || sec('agent skills', 'skills') || has(s.name, s.description, s.category))

  const show = {
    General: !q || sec('general', 'start', 'stop', 'flow control', 'condition', 'if / else', 'merge', 'split', 'loop'),
    Llm: !q || providers.some((p) => p.models.some((m) => llmMatch(p, m))),
    Tools: !q || toolOnlyItems.some(toolMatch) || customTools.some(toolMatch) || syntheticDataItems.length > 0 || sec('synthetic data'),
    Mcp: !q || mcpGroups.length > 0 || visibleCustomMcp.length > 0,
    Toolkit: !q || sec('toolkits', 'toolkit'),
    Memory: !q || memoryItems.length > 0,
    Cache: !q || cacheItems.length > 0,
    DocLoader: !q || allDocLoaders.some(loaderMatch),
    TextSplitter: !q || splitterItems.length > 0,
    Embedding: !q || embeddingItems.length > 0,
    VectorStore: !q || vectorStoreItems.length > 0,
    Retriever: !q || retrieverItems.length > 0,
    Reranker: !q || rerankerItems.length > 0,
    Middleware: !q || middlewareItems.length > 0,
    HumanGate: !q || humanGateItems.length > 0,
    Checkpointer: !q || checkpointerItems.length > 0,
    Workflow: !q || workflowItems.length > 0,
    OutputParser: !q || outputParserItems.length > 0,
    Agents: !q || agentItems.length > 0 || savedAgents.length > 0 || sec('agents', 'master'),
    KnowledgeBase: !q || sec('knowledge base') || kbItems.length > 0,
    Pipelines: !q || sec('pipelines', 'call pipeline', 'published'),
    Connections: !q || sec('connections') || connItems.length > 0,
    Skills: !q || sec('agent skills', 'skills') || skillItems.length > 0,
    Frameworks: !q || frameworkTools.length > 0,
  }
  const noResults = !!q && !Object.values(show).some(Boolean)

  const [groupsOpen, setGroupsOpen] = useState(readGroupsOpen)
  const setGroupOpen = (id: GroupId, value: boolean) => {
    setGroupsOpen((prev) => {
      const next = { ...prev, [id]: value }
      try { localStorage.setItem(GROUPS_STORAGE_KEY, JSON.stringify(next)) } catch { /* storage unavailable */ }
      return next
    })
  }
  const groupOpen = (id: GroupId) => (q ? true : groupsOpen[id])
  const toggleGroup = (id: GroupId) => setGroupOpen(id, !groupsOpen[id])

  // ⌘K / Ctrl+K focuses the search, expanding the panel first if it is collapsed.
  const searchRef = useRef<HTMLInputElement>(null)
  const focusAfterExpand = useRef(false)
  const expandAndFocusSearch = () => {
    focusAfterExpand.current = true
    onToggleCollapsed()
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        if (collapsed) {
          focusAfterExpand.current = true
          onToggleCollapsed()
        } else {
          searchRef.current?.focus()
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [collapsed, onToggleCollapsed])
  useEffect(() => {
    if (!collapsed && focusAfterExpand.current) {
      focusAfterExpand.current = false
      searchRef.current?.focus()
    }
  }, [collapsed])

  if (collapsed) {
    return (
      <aside className="panel panel-left panel-left--rail" aria-label="Node library">
        <button type="button" className="sidebar-rail-btn" title="Expand panel" aria-label="Expand panel" onClick={onToggleCollapsed}>»</button>
        <button type="button" className="sidebar-rail-btn" title="Search (⌘K)" aria-label="Search"
          onClick={expandAndFocusSearch}><NodeIcon kind="retriever" size={16} /></button>
        <span className="sidebar-rail-divider" />
        {GROUPS.map((g) => (
          <button key={g.id} type="button" className="sidebar-rail-btn" title={g.label} aria-label={g.label}
            onClick={() => { setGroupOpen(g.id, true); onToggleCollapsed() }}><NodeIcon kind={g.icon} size={16} /></button>
        ))}
      </aside>
    )
  }

  return (
    <aside className="panel panel-left" aria-label="Node library">
      {/* Global search across every section */}
      <div className="sidebar-top-row">
      <div className="provider-search-box global-search-box">
        <input type="text" className="search-input" ref={searchRef} placeholder="Search nodes, tools, models…"
          value={globalQuery} onChange={(e) => setGlobalQuery(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') setGlobalQuery('') }} />
        {globalQuery && (
          <button type="button" className="global-search-clear" title="Clear search" onClick={() => setGlobalQuery('')}>✕</button>
        )}
        {!globalQuery && <kbd className="global-search-kbd">⌘K</kbd>}
      </div>
      <button type="button" className="sidebar-collapse-btn" title="Collapse panel" aria-label="Collapse panel" onClick={onToggleCollapsed}>«</button>
      </div>
      {noResults && <p className="field-hint">No matches for “{globalQuery.trim()}”.</p>}

      <SidebarGroup id="essentials" label="Essentials" visible={show.General || show.Llm || show.Agents || show.Pipelines} isOpen={groupOpen('essentials')} onToggle={() => toggleGroup('essentials')}>
        {/* ── General (Start / Stop / Flow Control) ── */}
        <div className="section-title-row collapsible" hidden={!show.General} onClick={() => setIsGeneralSectionOpen(!isGeneralSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isGeneralSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="logic" />Start, stop & logic</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">6</span></div>
        </div>
        {show.General && open(isGeneralSectionOpen) && (
          <div className="section-body">
            <div className="pipeline-nodes-row">
              <div className="drag-card start-drag-card" draggable
                onDragStart={(e) => { e.dataTransfer.setData('application/univ-type', 'start') }}>
                <span className="node-icon">▶</span>
                <span className="drag-card-title">Start</span>
              </div>
              <div className="drag-card stop-drag-card" draggable
                onDragStart={(e) => { e.dataTransfer.setData('application/univ-type', 'stop') }}>
                <span className="node-icon">⏹</span>
                <span className="drag-card-title">Stop</span>
              </div>
            </div>

            {/* Flow Control chips */}
            <div className="gateway-section-label">Flow Control</div>
            <div className="tool-icon-grid">
              <div
                className="tool-icon-chip gateway-chip gateway-chip-condition"
                draggable
                onDragStart={(e) => {
                  e.stopPropagation()
                  e.dataTransfer.effectAllowed = 'move'
                  e.dataTransfer.setData('application/univ-type', 'gateway')
                  e.dataTransfer.setData('application/univ-gateway-kind', 'condition')
                }}
                title="Condition (IF/ELSE)&#10;Routes flow down the true branch or right on the false branch based on an expression."
              >
                <span className="tool-icon-emoji">◇</span>
                <span className="tool-icon-label">IF / ELSE</span>
              </div>
              <div
                className="tool-icon-chip gateway-chip gateway-chip-merge"
                draggable
                onDragStart={(e) => {
                  e.stopPropagation()
                  e.dataTransfer.effectAllowed = 'move'
                  e.dataTransfer.setData('application/univ-type', 'gateway')
                  e.dataTransfer.setData('application/univ-gateway-kind', 'merge')
                }}
                title="Merge&#10;Waits for all incoming branches and passes through when all arrive (AND-join)."
              >
                <span className="tool-icon-emoji">⊕</span>
                <span className="tool-icon-label">Merge</span>
              </div>
              <div
                className="tool-icon-chip gateway-chip gateway-chip-split"
                draggable
                onDragStart={(e) => {
                  e.stopPropagation()
                  e.dataTransfer.effectAllowed = 'move'
                  e.dataTransfer.setData('application/univ-type', 'gateway')
                  e.dataTransfer.setData('application/univ-gateway-kind', 'split')
                }}
                title="Split (Fan-out)&#10;Duplicates the output to N parallel branches simultaneously."
              >
                <span className="tool-icon-emoji">⑂</span>
                <span className="tool-icon-label">Split</span>
              </div>
              <div
                className="tool-icon-chip gateway-chip gateway-chip-loop"
                draggable
                onDragStart={(e) => {
                  e.stopPropagation()
                  e.dataTransfer.effectAllowed = 'move'
                  e.dataTransfer.setData('application/univ-type', 'gateway')
                  e.dataTransfer.setData('application/univ-gateway-kind', 'loop')
                }}
                title="Loop&#10;Repeats connected nodes up to max_iterations or until a stop condition is met."
              >
                <span className="tool-icon-emoji">↺</span>
                <span className="tool-icon-label">Loop</span>
              </div>
            </div>
          </div>
        )}
        {/* ── LLM Providers ── */}
        <div className="section-title-row collapsible" hidden={!show.Llm} onClick={() => setIsLlmSectionOpen(!isLlmSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isLlmSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="llm" />Models</span>
          </div>
          <div className="section-title-right">
            <span className="section-subcount">{providers.reduce((acc, p) => acc + p.models.length, 0)}</span>
          </div>
        </div>
        {show.Llm && open(isLlmSectionOpen) && (
          <div className="section-body">
            <div className="provider-search-box">
              <input type="text" className="search-input" placeholder="Search LLMs..."
                value={searchModelQuery} onChange={(e) => setSearchModelQuery(e.target.value)} />
            </div>
            <div className="providers-scroll-container">
              {providers.map((provider) => {
                const matchingModels = provider.models.filter((m) => llmMatch(provider, m))
                if (matchingModels.length === 0) return null
                const isGroupCollapsed = q ? false : (collapsedProviders[provider.id] ?? true)
                return (
                  <div key={provider.id} className="provider-group">
                    <div className="provider-group-header" onClick={() => toggleProviderGroup(provider.id)}>
                      <div className="provider-group-title-row">
                        <span className="group-chevron">{isGroupCollapsed ? '▶' : '▼'}</span>
                        <span className={`provider-logo provider-logo-${provider.id}`}>{getProviderIcon(provider.id)}</span>
                        <span className="provider-name">{provider.name}</span>
                      </div>
                      <span className="provider-count">{matchingModels.length}</span>
                    </div>
                    {!isGroupCollapsed && (
                      <div className="model-cards-list">
                        {matchingModels.map((modelName) => (
                          <div key={modelName} className="model-row" title={`Drag ${modelName} onto the canvas`}
                            draggable onDragStart={(e) => onDragStartLlm(e, provider.id, modelName)}>
                            <span className="model-row-name">{modelName}</span>
                            <span className="model-row-grip" aria-hidden="true">⋮⋮</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {/* ── Agents ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Agents} onClick={() => setIsAgentsSectionOpen(!isAgentsSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isAgentsSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="master_agent" />Agents</span>
          </div>
          {/* + 1 for the Master chip */}
          <div className="section-title-right"><span className="section-subcount">{agentItems.length + 1 + savedAgents.length}</span></div>
        </div>
        {show.Agents && open(isAgentsSectionOpen) && (
          <div className="section-body">
            {agentCatalog.groups.map((group) => {
              const items = agentItems.filter((p) => p.group === group)
              const withMaster = group === 'Orchestration'
              if (items.length === 0 && !withMaster) return null
              return (
                <div key={group} className="tool-group">
                  <button type="button" className="tool-group-header" onClick={() => toggleAgentGroup(group)}
                    aria-expanded={agentGroupOpen(group)}>
                    <span className="tool-group-chevron">{agentGroupOpen(group) ? '▾' : '▸'}</span>
                    <span className="tool-group-name">{group}</span>
                    <span className="tool-group-count">{items.length + (withMaster ? 1 : 0)}</span>
                  </button>
                  {agentGroupOpen(group) && (
                    <div className="tool-icon-grid">
                      {withMaster && (
                        <div
                          className="tool-icon-chip"
                          draggable
                          onDragStart={(e) => {
                            e.dataTransfer.setData('application/univ-type', 'master_agent')
                            e.dataTransfer.setData('application/univ-agent-strategy', 'sequential')
                            e.dataTransfer.effectAllowed = 'move'
                          }}
                          title="Master Agent\nOrchestrator that receives a high-level goal and delegates tasks to Child Agents."
                        >
                          <span className="tool-icon-emoji">👑</span>
                          <span className="tool-icon-label">Master</span>
                        </div>
                      )}
                      {items.map((agent) => (
                        <div
                          key={agent.id}
                          className="tool-icon-chip"
                          draggable
                          onDragStart={(e) => {
                            if (agent.starter) {
                              e.dataTransfer.setData('application/univ-type', 'child_agent')
                              e.dataTransfer.setData('application/univ-agent-role', agent.role)
                              if (agent.kind !== 'llm') e.dataTransfer.setData('application/univ-agent-kind', agent.kind)
                            } else {
                              e.dataTransfer.setData('application/univ-type', 'builtin_agent')
                              e.dataTransfer.setData('application/univ-builtin-agent', JSON.stringify(agent))
                            }
                            e.dataTransfer.setData('application/univ-agent-builtin', agent.id)
                            e.dataTransfer.effectAllowed = 'move'
                          }}
                          title={`${agent.name} Agent\n${agent.description}${agent.ready ? '' : `\n⚠ Needs tools: ${agent.missing_tools.join(', ')} (Settings → Agents)`}`}
                        >
                          <span className="tool-icon-emoji">{agent.icon}</span>
                          <span className="tool-icon-label">{agent.name}{agent.ready ? '' : ' ⚠'}</span>
                          {agent.is_new && <span className="tool-icon-new">New</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
            {savedAgents.length > 0 && (
              <div className="tool-group">
                <button type="button" className="tool-group-header" onClick={() => toggleAgentGroup('Saved agents')}
                  aria-expanded={agentGroupOpen('Saved agents')}>
                  <span className="tool-group-chevron">{agentGroupOpen('Saved agents') ? '▾' : '▸'}</span>
                  <span className="tool-group-name">Saved agents</span>
                  <span className="tool-group-count">{savedAgents.length}</span>
                </button>
                {agentGroupOpen('Saved agents') && (
                  <div className="tool-icon-grid">
                    {savedAgents.map((agent) => (
                      <div
                        key={agent.id}
                        className="tool-icon-chip"
                        draggable
                        onDragStart={(e) => {
                          e.dataTransfer.setData('application/univ-type', 'saved_agent')
                          e.dataTransfer.setData('application/univ-saved-agent', JSON.stringify(agent))
                          e.dataTransfer.effectAllowed = 'move'
                        }}
                        title={`${agent.name} (v${agent.version})\n${agent.description || `${agent.spec.tools.length} tool(s), ${agent.spec.skills.length} skill(s)`}`}
                      >
                        <span className="tool-icon-emoji">{agent.icon}</span>
                        <span className="tool-icon-label">{agent.name}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {onManageAgents && (
              <button type="button" className="sidebar-packages-btn" onClick={onManageAgents}>
                {moreAgents > 0 ? `📦 Browse ${moreAgents} more agents` : '📦 Manage agents'}
              </button>
            )}
          </div>
        )}
        {/* ── Pipelines (published, runnable) ── */}
        {show.Pipelines && <PipelinesSection isOpen={open(isPipelinesSectionOpen)} setIsOpen={setIsPipelinesSectionOpen} />}
      </SidebarGroup>
      <SidebarGroup id="tools" label="Tools & integrations" visible={show.Tools || show.Mcp || show.Toolkit || show.Skills || show.Connections || show.Frameworks} isOpen={groupOpen('tools')} onToggle={() => toggleGroup('tools')}>
        {/* ── Tools (built-in + custom) ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Tools} onClick={() => setIsToolsSectionOpen(!isToolsSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isToolsSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="tool" />Tools</span>
          </div>
          <div className="section-title-right">
            <span className="section-subcount">{toolOnlyItems.length + customTools.length}</span>
          </div>
        </div>
        {show.Tools && open(isToolsSectionOpen) && (
          <div className="section-body">
            <div className="provider-search-box">
              <input type="text" className="search-input" placeholder="Search tools..."
                value={searchToolQuery} onChange={(e) => setSearchToolQuery(e.target.value)} />
            </div>
            <div className="tools-scroll-container">
              {toolGroups.map((group) => (
                <div key={group.name} className="tool-group">
                  <button type="button" className="tool-group-header" onClick={() => toggleToolGroup(group.name)}
                    aria-expanded={toolGroupOpen(group.name)}>
                    <span className="tool-group-chevron">{toolGroupOpen(group.name) ? '▾' : '▸'}</span>
                    <span className="tool-group-name">{group.name}</span>
                    <span className="tool-group-count">{group.tools.length}</span>
                  </button>
                  {toolGroupOpen(group.name) && (
                    <div className="tool-icon-grid">
                      {group.tools.map((tool) => (
                        <div
                          key={tool.id}
                          className="tool-icon-chip"
                          draggable
                          onDragStart={(e) => onDragStartTool(e, tool)}
                          title={`${tool.name}\n${tool.description}`}
                        >
                          <span className="tool-icon-emoji">{tool.icon}</span>
                          <span className="tool-icon-label">{tool.name}</span>
                          {tool.is_new && <span className="tool-icon-new">New</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {visibleCustomTools.length > 0 && (
                <div className="tool-group">
                  <button type="button" className="tool-group-header" onClick={() => toggleToolGroup('Custom')}
                    aria-expanded={toolGroupOpen('Custom')}>
                    <span className="tool-group-chevron">{toolGroupOpen('Custom') ? '▾' : '▸'}</span>
                    <span className="tool-group-name">Custom</span>
                    <span className="tool-group-count">{visibleCustomTools.length}</span>
                  </button>
                  {toolGroupOpen('Custom') && (
                    <div className="tool-icon-grid">
                        {/* Custom tools — shown in same grid with a dashed border accent */}
                        {visibleCustomTools.map((ct) => (
                            <div
                              key={`custom_${ct.id}`}
                              className="tool-icon-chip tool-icon-chip-custom"
                              draggable
                              onDragStart={(e) => {
                                e.dataTransfer.effectAllowed = 'move'
                                e.dataTransfer.setData('application/univ-type', 'tool')
                                e.dataTransfer.setData('application/univ-tool-data', JSON.stringify({
                                  id: `custom_${ct.id}`, name: ct.name, type: 'tool' as const,
                                  icon: ct.icon, description: ct.description,
                                  default_config: Object.fromEntries(ct.config_keys.map((k) => [k, ''])),
                                }))
                              }}
                              title={`[Custom] ${ct.name}\n${ct.description}`}
                            >
                              <span className="tool-icon-emoji">{ct.icon}</span>
                              <span className="tool-icon-label">{ct.name}</span>
                              {isRecentlyAdded(ct.created_at) && <span className="tool-icon-new">New</span>}
                              <div className="tool-icon-chip-actions">
                                <button
                                  type="button"
                                  className="ct-card-action-btn"
                                  title="Edit tool code"
                                  onClick={(e) => { e.stopPropagation(); onEditCustomTool(ct) }}
                                ><Pencil aria-hidden="true" /></button>
                                <button
                                  type="button"
                                  className="ct-card-action-btn delete"
                                  title="Delete tool"
                                  onClick={(e) => { e.stopPropagation(); onDeleteCustomTool(ct) }}
                                ><Trash2 aria-hidden="true" /></button>
                              </div>
                            </div>
                          ))}
                    </div>
                  )}
                </div>
              )}
              {toolsError ? <CatalogError message={toolsError} onRetry={onRetryTools} />
                : toolGroups.length === 0 && visibleCustomTools.length === 0 && (
                  <p className="field-hint">No tools match your search.</p>
                )}
            </div>
            {onManagePackages && (
              <button type="button" className="sidebar-packages-btn" onClick={onManagePackages}>
                {moreTools > 0 ? `📦 Browse ${moreTools} more tools` : '📦 Manage tool packages'}
              </button>
            )}
            <button
              type="button"
              className="tools-create-btn"
              onClick={onOpenCustomToolModal}
            >
              + Create Custom Tool
            </button>
          </div>
        )}
        {/* ── MCP Servers ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Mcp}
          onClick={() => { setIsMcpSectionOpen(!isMcpSectionOpen); if (!isMcpSectionOpen) fetchCustomMcpServers() }}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isMcpSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="mcp" />MCP Servers</span>
          </div>
          <div className="section-title-right">
            <span className="section-subcount">{mcpItems.length + customMcpServers.length}</span>
          </div>
        </div>
        {show.Mcp && open(isMcpSectionOpen) && (
          <div className="section-body">
            <button type="button" className="ct-new-tool-btn" onClick={onOpenCustomMcpModal}>
              + Add Custom MCP Server
            </button>
            {onManagePackages && (
              <button type="button" className="sidebar-packages-btn" onClick={onManagePackages}>
                {moreMcp > 0 ? `📦 Browse ${moreMcp} more MCP servers` : '📦 Manage MCP packages'}
              </button>
            )}
            <div className="provider-search-box" style={{ marginTop: 8 }}>
              <input type="text" className="search-input" placeholder="Search MCP servers..."
                value={searchMcpQuery} onChange={(e) => setSearchMcpQuery(e.target.value)} />
            </div>
            <div className="tools-scroll-container">
              {mcpGroups.map((group) => (
                <div key={group.name} className="tool-group">
                  <button type="button" className="tool-group-header" onClick={() => toggleMcpGroup(group.name)}
                    aria-expanded={mcpGroupOpen(group.name)}>
                    <span className="tool-group-chevron">{mcpGroupOpen(group.name) ? '▾' : '▸'}</span>
                    <span className="tool-group-name">{group.name}</span>
                    <span className="tool-group-count">{group.tools.length}</span>
                  </button>
                  {mcpGroupOpen(group.name) && (
                    <div className="tool-icon-grid">
                      {group.tools.map((tool) => (
                        <div
                          key={tool.id}
                          className="tool-icon-chip mcp"
                          draggable
                          onDragStart={(e) => onDragStartTool(e, tool)}
                          title={`[MCP] ${tool.name}\n${tool.description}`}
                        >
                          <span className="tool-icon-emoji">{tool.icon}</span>
                          <span className="tool-icon-label">{tool.name}</span>
                          {tool.is_new && <span className="tool-icon-new">New</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
              {visibleCustomMcp.length > 0 && (
                <div className="tool-group">
                  <button type="button" className="tool-group-header" onClick={() => toggleMcpGroup('Custom')}
                    aria-expanded={mcpGroupOpen('Custom')}>
                    <span className="tool-group-chevron">{mcpGroupOpen('Custom') ? '▾' : '▸'}</span>
                    <span className="tool-group-name">Custom</span>
                    <span className="tool-group-count">{visibleCustomMcp.length}</span>
                  </button>
                  {mcpGroupOpen('Custom') && (
                    <div className="tool-icon-grid">
                      {visibleCustomMcp.map((s) => (
                        <div
                          key={s.id}
                          className="tool-icon-chip mcp custom"
                          draggable
                          onDragStart={(e) => onDragStartTool(e, {
                            id: s.id, name: s.name, type: 'mcp', icon: s.icon,
                            description: s.description || `${s.transport.toUpperCase()}: ${s.command || s.url}`,
                            default_config: { transport: s.transport, command: s.command, args: s.args, url: s.url },
                          })}
                          title={`[Custom MCP] ${s.name}\n${s.description || `${s.transport.toUpperCase()}: ${s.command || s.url}`}`}
                        >
                          <span className="tool-icon-emoji">{s.icon}</span>
                          <span className="tool-icon-label">{s.name}</span>
                          {isRecentlyAdded(s.created_at) && <span className="tool-icon-new">New</span>}
                          <div className="tool-icon-chip-actions">
                            <button type="button" className="ct-card-action-btn" title="Edit" onClick={(e) => { e.stopPropagation(); onEditCustomMcp(s) }}><Pencil aria-hidden="true" /></button>
                            <button type="button" className="ct-card-action-btn delete" title="Delete" onClick={(e) => { e.stopPropagation(); onDeleteCustomMcp(s) }}><Trash2 aria-hidden="true" /></button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {toolsError ? <CatalogError message={toolsError} onRetry={onRetryTools} />
                : mcpGroups.length === 0 && visibleCustomMcp.length === 0 && (
                  <p className="field-hint">No MCP servers match your search.</p>
                )}
            </div>
          </div>
        )}
        {/* ── Toolkits ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Toolkit} onClick={() => setIsToolkitSectionOpen(!isToolkitSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isToolkitSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="toolkit" />Toolkits</span>
          </div>
          <div className="section-title-right"><span className="section-subcount" /></div>
        </div>
        {show.Toolkit && open(isToolkitSectionOpen) && (
          <div className="section-body">
            <div className="toolkit-cards-list">
              <div className="drag-card toolkit-drag-card" draggable onDragStart={onDragStartToolkit}>
                <div className="drag-card-header">
                  <span className="tool-card-title-row">
                    <span className="tool-card-icon">🗂️</span>
                    <span className="drag-card-title">New Toolkit</span>
                  </span>
                  <span className="chip chip-toolkit">TOOLKIT</span>
                </div>
                <p className="tool-card-desc">
                  A container for multiple tools. Drag onto the canvas, then drop individual tool cards onto it to build your toolkit.
                </p>
                <div className="drag-card-footer-info">
                  <span className="drag-handle-hint">:: Drag to canvas</span>
                </div>
              </div>
            </div>
            <p className="toolkit-sidebar-hint">
              After placing the Toolkit node, drag any Tool or MCP card from the sections above and drop it <strong>directly onto the Toolkit node</strong> to add it as a sub-tool.
            </p>
          </div>
        )}
        {/* ── Skills (Packaged Capabilities & SOPs) ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Skills} onClick={() => setIsSkillsSectionOpen(!isSkillsSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isSkillsSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="skill" />Agent Skills</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">{skills.length}</span></div>
        </div>
        {show.Skills && open(isSkillsSectionOpen) && (
          <div className="section-body">
            <button
              type="button"
              className="btn btn-secondary full-width"
              onClick={onOpenSkillsModal}
              style={{ marginBottom: 8 }}
            >
              ⚡ Manage Skills Catalog
            </button>
            <div className="rag-cards-list">
              {skillItems.map((skill) => (
                <div
                  key={skill.id}
                  className="drag-card connection-card skill-card"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'skill')
                    e.dataTransfer.setData('application/univ-skill-data', JSON.stringify(skill))
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                >
                  <div className="drag-card-header">
                    <span className="tool-card-title-row">
                      <span className="tool-card-icon">{skill.icon || '⚡'}</span>
                      <span className="drag-card-title">{skill.name}</span>
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span className="chip chip-skill">
                        {skill.category.toUpperCase()}
                      </span>
                    </div>
                  </div>
                  <p className="tool-card-desc">
                    {skill.description || skill.instructions.slice(0, 70)}
                  </p>
                  <div className="drag-card-footer-info"><span className="drag-handle-hint">:: Drag to canvas</span></div>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Connections ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Connections}
          onClick={() => { setIsConnectionsSectionOpen(!isConnectionsSectionOpen); if (!isConnectionsSectionOpen) fetchConnections() }}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isConnectionsSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="connection" />Connections</span>
          </div>
          <div className="section-title-right">
            <span className="section-subcount">{connections.length || null}</span>
          </div>
        </div>
        {show.Connections && open(isConnectionsSectionOpen) && (
          <div className="section-body">
            <button type="button" className="ct-new-tool-btn" onClick={onOpenConnectionModal}>
              + Add Connection (Postgres, MySQL, MongoDB, Redis, S3...)
            </button>
            {connections.length === 0 && (
              <p className="field-hint" style={{ marginTop: 8 }}>
                No active connections yet. Connect PostgreSQL, MySQL, MongoDB, Redis, Snowflake, AWS S3, or REST APIs to reuse across RAG loaders and SQL tools.
              </p>
            )}
            <div className="rag-cards-list" style={{ marginTop: 8 }}>
              {connItems.map((conn) => (
                <div key={conn.id} className="drag-card connection-card connection-card--compact" draggable
                  title={`${conn.status_msg ? conn.status_msg + '\n' : ''}Drag to canvas`}
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'connection')
                    e.dataTransfer.setData('application/univ-connection-data', JSON.stringify(conn))
                    e.dataTransfer.effectAllowed = 'move'
                  }}>
                  <div className="connection-card-row">
                    <ConnectionIcon type={conn.type} />
                    <div className="connection-card-text">
                      <span className="connection-card-name">{conn.name}</span>
                      <span className="connection-card-meta">
                        <span className={`connection-status-dot is-${conn.status}`} aria-label={conn.status} />
                        {conn.description || `${conn.type.toUpperCase()} · ${conn.config?.host || conn.config?.account || conn.config?.bucket || conn.config?.base_url || 'Configured'}`}
                      </span>
                    </div>
                    <div className="connection-card-actions">
                      <button type="button" className="ct-card-action-btn" title="Edit"
                        onClick={(e) => { e.stopPropagation(); onEditConnection(conn) }}><Pencil aria-hidden="true" /></button>
                      <button type="button" className="ct-card-action-btn delete" title="Delete"
                        onClick={(e) => { e.stopPropagation(); onDeleteConnection(conn) }}><Trash2 aria-hidden="true" /></button>
                    </div>
                  </div>
                  {conn.status === 'error' && conn.status_msg && (
                    <div className="connection-card-error">{conn.status_msg}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Frameworks ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Frameworks} onClick={() => setIsFrameworksSectionOpen(!isFrameworksSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isFrameworksSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="frameworks" />Frameworks</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">8</span></div>
        </div>
        {show.Frameworks && open(isFrameworksSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {frameworkTools
                .map((tool) => (
                  <div
                    key={tool.id}
                    className="tool-icon-chip"
                    draggable
                    onDragStart={(e) => onDragStartTool(e, tool)}
                    title={`${tool.name}\n${tool.description}`}
                  >
                    <span className="tool-icon-emoji">{tool.icon}</span>
                    <span className="tool-icon-label">{tool.name}</span>
                    {tool.is_new && <span className="tool-icon-new">New</span>}
                  </div>
                ))}
            </div>
          </div>
        )}
        {/* ── Synthetic Data ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Tools || syntheticDataItems.length === 0} onClick={() => setIsSyntheticDataSectionOpen(!isSyntheticDataSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isSyntheticDataSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="synthetic_data" />Synthetic Data</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">{SYNTHETIC_DATA_PRESETS.length}</span></div>
        </div>
        {show.Tools && syntheticDataItems.length > 0 && open(isSyntheticDataSectionOpen) && (
          <div className="section-body">
            {syntheticGroups.map((group) => (
              <div key={group.name} className="tool-group">
                <button type="button" className="tool-group-header" onClick={() => toggleSyntheticGroup(group.name)}
                  aria-expanded={syntheticGroupOpen(group.name)} title={`Synthetic category: ${group.name}`}>
                  <span className="tool-group-chevron">{syntheticGroupOpen(group.name) ? '▾' : '▸'}</span>
                  <span className="tool-group-name">{group.name}</span>
                  <span className="tool-group-count">{group.presets.length}</span>
                </button>
                {syntheticGroupOpen(group.name) && (
                  <div className="tool-icon-grid">
                    {group.presets.map((preset) => (
                      <div
                        key={preset.id}
                        className="tool-icon-chip"
                        draggable
                        onDragStart={(e) => {
                          e.stopPropagation()
                          e.dataTransfer.effectAllowed = 'move'
                          e.dataTransfer.setData('application/univ-type', 'synthetic_data')
                          e.dataTransfer.setData('application/univ-synth-preset', preset.id)
                          e.dataTransfer.setData('application/univ-label', preset.label)
                        }}
                        title={`${preset.label}\n${preset.desc}`}
                      >
                        <span className="tool-icon-emoji">{preset.icon}</span>
                        <span className="tool-icon-label">{preset.label}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </SidebarGroup>
      <SidebarGroup id="knowledge" label="Knowledge (RAG)" visible={show.KnowledgeBase || show.DocLoader || show.TextSplitter || show.Embedding || show.VectorStore || show.Retriever || show.Reranker} isOpen={groupOpen('knowledge')} onToggle={() => toggleGroup('knowledge')}>
        {/* ── Knowledge Bases ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.KnowledgeBase}
          onClick={() => { setIsKnowledgeBaseSectionOpen(!isKnowledgeBaseSectionOpen); if (!isKnowledgeBaseSectionOpen) fetchKnowledgeBases() }}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isKnowledgeBaseSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="knowledge_base" />Knowledge Base</span>
          </div>
          <div className="section-title-right">
            <span className="section-subcount">{knowledgeBases.length || null}</span>
          </div>
        </div>
        {show.KnowledgeBase && open(isKnowledgeBaseSectionOpen) && (
          <div className="section-body">
            <button type="button" className="ct-new-tool-btn" onClick={onOpenKnowledgeBaseModal}>
              + Create Knowledge Base (PDF, Text, URL)
            </button>
            {knowledgeBases.length === 0 && (
              <p className="field-hint" style={{ marginTop: 8 }}>
                No knowledge bases created yet. Index documentation, policies, or manuals to provide context for your agents.
              </p>
            )}
            <div className="rag-cards-list" style={{ marginTop: 8 }}>
              {kbItems.map((kb) => (
                <div key={kb.id} className="drag-card kb-card" draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'knowledge_base')
                    e.dataTransfer.setData('application/univ-kb-data', JSON.stringify(kb))
                    e.dataTransfer.effectAllowed = 'move'
                  }}>
                  <div className="drag-card-header">
                    <span className="tool-card-title-row">
                      <span className="tool-card-icon">{kb.icon}</span>
                      <span className="drag-card-title">{kb.name}</span>
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <span className="chip chip-kb">{kb.chunk_count} CHUNKS</span>
                      <button type="button" className="ct-card-action-btn delete" title="Delete"
                        onClick={(e) => { e.stopPropagation(); onDeleteKnowledgeBase(kb) }}><Trash2 aria-hidden="true" /></button>
                    </div>
                  </div>
                  <p className="tool-card-desc">{kb.description || `Source: ${kb.source_detail}`}</p>
                  <div className="drag-card-footer-info"><span className="drag-handle-hint">:: Drag to canvas</span></div>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Document Loaders ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.DocLoader} onClick={() => setIsDocLoaderSectionOpen(!isDocLoaderSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isDocLoaderSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="doc_loader" />Document Loaders</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">{allDocLoaders.length}</span></div>
        </div>
        {show.DocLoader && open(isDocLoaderSectionOpen) && (
          <div className="section-body">
            <button type="button" className="ct-new-tool-btn" onClick={() => setDocLoaderModal({ open: true })}>
              + Add Custom Document Loader
            </button>
            <div className="provider-search-box" style={{ marginTop: 8 }}>
              <input type="text" className="search-input" placeholder="Search document loaders..."
                value={searchLoaderQuery} onChange={(e) => setSearchLoaderQuery(e.target.value)} />
            </div>
            <div className="tools-scroll-container">
              {loaderGroups.map((group) => (
                <div key={group.name} className="tool-group">
                  <button type="button" className="tool-group-header" onClick={() => toggleLoaderGroup(group.name)}
                    aria-expanded={loaderGroupOpen(group.name)}>
                    <span className="tool-group-chevron">{loaderGroupOpen(group.name) ? '▾' : '▸'}</span>
                    <span className="tool-group-name">{group.name}</span>
                    <span className="tool-group-count" title={`${group.ready} ready, ${group.loaders.length - group.ready} coming soon`}>
                      {group.ready === group.loaders.length ? group.loaders.length : `${group.ready}/${group.loaders.length}`}
                    </span>
                  </button>
                  {loaderGroupOpen(group.name) && (
                    <div className="tool-icon-grid">
                      {group.loaders.map((preset) => {
                        const live = preset.custom || preset.available !== false
                        return (
                          <div
                            key={preset.type}
                            className={`tool-icon-chip${preset.custom ? ' custom' : ''}${live ? '' : ' soon'}`}
                            draggable={live}
                            onDragStart={(e) => {
                              if (!live) { e.preventDefault(); return }
                              e.dataTransfer.setData('application/univ-type', 'doc_loader')
                              e.dataTransfer.setData('application/univ-loader-type', preset.type)
                              e.dataTransfer.effectAllowed = 'move'
                            }}
                            title={`${preset.custom ? '[Custom] ' : ''}${preset.label}\n${preset.desc}${live ? '' : '\nComing soon — not available yet'}`}
                          >
                            <span className="tool-icon-emoji">{preset.icon}</span>
                            <span className="tool-icon-label">{preset.label}</span>
                            {!live && <span className="tool-icon-soon">Soon</span>}
                            {preset.custom && (
                              <div className="tool-icon-chip-actions">
                                <button type="button" className="ct-card-action-btn" title="Edit"
                                  onClick={(e) => { e.stopPropagation(); setDocLoaderModal({ open: true, loader: preset }) }}><Pencil aria-hidden="true" /></button>
                                <button type="button" className="ct-card-action-btn delete" title="Delete"
                                  onClick={(e) => { e.stopPropagation(); if (window.confirm(`Delete custom loader "${preset.label}"?`)) deleteCustomDocLoader(preset.type) }}><Trash2 aria-hidden="true" /></button>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              ))}
              {loaderGroups.length === 0 && <p className="field-hint">No document loaders match your search.</p>}
            </div>
          </div>
        )}
        {docLoaderModal.open && (
          <CustomDocLoaderModal
            loader={docLoaderModal.loader}
            onClose={() => setDocLoaderModal({ open: false })}
            onSaved={() => setDocLoaderModal({ open: false })}
          />
        )}
        {/* ── Text Splitters ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.TextSplitter} onClick={() => setIsTextSplitterSectionOpen(!isTextSplitterSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isTextSplitterSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="text_splitter" />Text Splitters</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">6</span></div>
        </div>
        {show.TextSplitter && open(isTextSplitterSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {splitterItems.map((preset) => (
                <div
                  key={preset.splitter_type}
                  className="tool-icon-chip"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'text_splitter')
                    e.dataTransfer.setData('application/univ-splitter-type', preset.splitter_type)
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Embeddings ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Embedding} onClick={() => setIsEmbeddingSectionOpen(!isEmbeddingSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isEmbeddingSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="embedding" />Embeddings</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">11</span></div>
        </div>
        {show.Embedding && open(isEmbeddingSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {embeddingItems.map((preset) => (
                <div
                  key={preset.provider}
                  className="tool-icon-chip"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'embedding')
                    e.dataTransfer.setData('application/univ-emb-provider', preset.provider)
                    e.dataTransfer.setData('application/univ-emb-model', preset.model)
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Vector Stores ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.VectorStore} onClick={() => setIsVectorStoreSectionOpen(!isVectorStoreSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isVectorStoreSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="vector_store" />Vector Stores</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">{VECTOR_STORE_PRESETS.length}</span></div>
        </div>
        {show.VectorStore && open(isVectorStoreSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {vectorStoreItems.map((preset) => {
                const live = LIVE_VECTOR_STORES.has(preset.store_type)
                return (
                  <div
                    key={preset.store_type}
                    className={`tool-icon-chip${live ? '' : ' soon'}`}
                    draggable={live}
                    onDragStart={live ? (e) => {
                      e.dataTransfer.setData('application/univ-type', 'vector_store')
                      e.dataTransfer.setData('application/univ-store-type', preset.store_type)
                      e.dataTransfer.effectAllowed = 'move'
                    } : undefined}
                    title={`${preset.label}${live ? '' : ' — coming soon'}\n${preset.desc}`}
                  >
                    {!live && <span className="tool-icon-soon">Soon</span>}
                    <span className="tool-icon-emoji">{preset.icon}</span>
                    <span className="tool-icon-label">{preset.label}</span>
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {/* ── Retrievers ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Retriever} onClick={() => setIsRetrieverSectionOpen(!isRetrieverSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isRetrieverSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="retriever" />Retrievers</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">7</span></div>
        </div>
        {show.Retriever && open(isRetrieverSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {retrieverItems.map((preset) => (
                <div
                  key={preset.search_type}
                  className="tool-icon-chip"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'retriever')
                    e.dataTransfer.setData('application/univ-retriever-type', preset.search_type)
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Reranker ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Reranker} onClick={() => setIsRerankerSectionOpen(!isRerankerSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isRerankerSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="reranker" />Rerankers</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">4</span></div>
        </div>
        {show.Reranker && open(isRerankerSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {rerankerItems.map((preset) => (
                <div key={preset.reranker_type} className="tool-icon-chip" draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'reranker')
                    e.dataTransfer.setData('application/univ-reranker-type', preset.reranker_type)
                    e.dataTransfer.setData('application/univ-reranker-model', preset.model)
                    e.dataTransfer.setData('application/univ-reranker-topn', String(preset.top_n))
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </SidebarGroup>
      <SidebarGroup id="control" label="Control & safety" visible={show.Memory || show.Cache || show.Middleware || show.HumanGate || show.Checkpointer || show.Workflow || show.OutputParser} isOpen={groupOpen('control')} onToggle={() => toggleGroup('control')}>
        {/* ── Memory ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Memory} onClick={() => setIsMemorySectionOpen(!isMemorySectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isMemorySectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="memory" />Memory</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">5</span></div>
        </div>
        {show.Memory && open(isMemorySectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {memoryItems.map((preset) => (
                <div
                  key={preset.strategy}
                  className="tool-icon-chip"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'memory')
                    e.dataTransfer.setData('application/univ-memory-strategy', preset.strategy)
                    e.dataTransfer.setData('application/univ-memory-budget', String(preset.token_budget))
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Cache ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Cache} onClick={() => setIsCacheSectionOpen(!isCacheSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isCacheSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="cache" />Cache</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">3</span></div>
        </div>
        {show.Cache && open(isCacheSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {cacheItems.map((preset) => (
                <div
                  key={preset.scope}
                  className="tool-icon-chip"
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'cache')
                    e.dataTransfer.setData('application/univ-cache-scope', preset.scope)
                    e.dataTransfer.setData('application/univ-cache-ttl', String(preset.ttl_seconds))
                    e.dataTransfer.setData('application/univ-cache-max', String(preset.max_size))
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Guardrails (middleware nodes) ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Middleware} onClick={() => setIsMiddlewareSectionOpen(!isMiddlewareSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isMiddlewareSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="middleware" />Guardrails</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">{MIDDLEWARE_PRESETS.length}</span></div>
        </div>
        {show.Middleware && open(isMiddlewareSectionOpen) && (
          <div className="section-body">
            {MIDDLEWARE_GROUPS.map((group) => {
              const items = middlewareItems.filter((p) => p.group === group)
              if (!items.length) return null
              return (
                <div key={group} className="guardrail-group">
                  <div className="guardrail-group-label">{group}</div>
                  <div className="tool-icon-grid">
                    {items.map((preset) => (
                      <div key={preset.mw_type} className="tool-icon-chip" draggable
                        onDragStart={(e) => {
                          e.dataTransfer.setData('application/univ-type', 'middleware')
                          e.dataTransfer.setData('application/univ-mw-type', preset.mw_type)
                          e.dataTransfer.effectAllowed = 'move'
                        }}
                        title={`${preset.label}\n${preset.desc}`}
                      >
                        <span className="tool-icon-emoji">{preset.icon}</span>
                        <span className="tool-icon-label">{preset.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}
        {/* ── Human Gate ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.HumanGate} onClick={() => setIsHumanGateSectionOpen(!isHumanGateSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isHumanGateSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="human_gate" />Human-in-the-Loop</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">3</span></div>
        </div>
        {show.HumanGate && open(isHumanGateSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {humanGateItems.map((preset) => (
                <div key={preset.gate_type} className="tool-icon-chip" draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'human_gate')
                    e.dataTransfer.setData('application/univ-gate-type', preset.gate_type)
                    e.dataTransfer.setData('application/univ-gate-timeout', String(preset.timeout_hours))
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Checkpointer ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Checkpointer} onClick={() => setIsCheckpointerSectionOpen(!isCheckpointerSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isCheckpointerSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="checkpointer" />Checkpointing</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">3</span></div>
        </div>
        {show.Checkpointer && open(isCheckpointerSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {checkpointerItems.map((preset) => (
                <div key={preset.mode} className="tool-icon-chip" draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'checkpointer')
                    e.dataTransfer.setData('application/univ-checkpoint-mode', preset.mode)
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Workflow Steps ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.Workflow} onClick={() => setIsWorkflowSectionOpen(!isWorkflowSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isWorkflowSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="wf_step" />Workflow Steps</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">5</span></div>
        </div>
        {show.Workflow && open(isWorkflowSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {workflowItems.map((preset) => (
                <div key={preset.step_type} className="tool-icon-chip" draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'wf_step')
                    e.dataTransfer.setData('application/univ-wf-step-type', preset.step_type)
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        {/* ── Output Parser ── */}
        <div className="section-title-row collapsible mt-section" hidden={!show.OutputParser} onClick={() => setIsOutputParserSectionOpen(!isOutputParserSectionOpen)}>
          <div className="section-title-left">
            <span className="section-chevron">{open(isOutputParserSectionOpen) ? '▼' : '▶'}</span>
            <span className="section-heading"><NodeIcon kind="output_parser" />Output Parsers</span>
          </div>
          <div className="section-title-right"><span className="section-subcount">6</span></div>
        </div>
        {show.OutputParser && open(isOutputParserSectionOpen) && (
          <div className="section-body">
            <div className="tool-icon-grid">
              {outputParserItems.map((preset) => (
                <div key={preset.parser_type} className="tool-icon-chip" draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('application/univ-type', 'output_parser')
                    e.dataTransfer.setData('application/univ-parser-type', preset.parser_type)
                    e.dataTransfer.effectAllowed = 'move'
                  }}
                  title={`${preset.label}\n${preset.desc}`}
                >
                  <span className="tool-icon-emoji">{preset.icon}</span>
                  <span className="tool-icon-label">{preset.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </SidebarGroup>

      {!q && recentNodes.length > 0 && (
        <div className="sidebar-recent">
          <div className="sidebar-recent-title">Recently used</div>
          {recentNodes.map((r) => (
            <div key={JSON.stringify(r.payload)} className="sidebar-recent-item" draggable title="Drag onto the canvas"
              onDragStart={(e) => {
                Object.entries(r.payload).forEach(([k, v]) => e.dataTransfer.setData(k, v))
                e.dataTransfer.effectAllowed = 'move'
              }}>
              <span className="sidebar-recent-icon"><NodeIcon kind={r.type} size={13} /></span>
              <span className="sidebar-recent-label">{r.label}</span>
            </div>
          ))}
        </div>
      )}
    </aside>
  )
}
