/**
 * useCatalogData — fetches and manages all catalog/remote data:
 * LLM providers, tool categories, custom tools, custom MCP servers,
 * connections, and knowledge bases.
 */
import { useState, useCallback } from 'react'
import type {
  ProviderOption,
  ToolCategory,
  AppRecord,
  KnowledgeBaseRecord,
  ConnectionRecord,
  SkillRecord,
} from '../types'
import { API_BASE } from '../types'
import type { CustomMcpRecord } from '../types'
import { setToolCatalog } from '../utils/toolCatalog'
import { setDocLoaderCatalog } from '../utils/docLoaders'

const DEFAULT_PROVIDERS: ProviderOption[] = [
  { id: 'openai',       name: 'OpenAI',               models: ['gpt-5.5', 'gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-4.1', 'gpt-4o', 'gpt-4o-mini', 'o3', 'o4-mini'] },
  { id: 'anthropic',    name: 'Anthropic',            models: ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5', 'claude-fable-5-1'] },
  { id: 'groq',         name: 'Groq (ultra-fast)',    models: ['openai/gpt-oss-120b', 'openai/gpt-oss-20b', 'qwen/qwen3.8-27b'] },
  { id: 'gemini',       name: 'Google Gemini',        models: ['gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-pro-preview', 'gemini-2.5-pro', 'gemini-2.5-flash'] },
  { id: 'mistral',      name: 'Mistral AI',           models: ['mistral-large-latest', 'mistral-medium-latest', 'mistral-small-latest', 'codestral-latest'] },
  { id: 'together',     name: 'Together AI',          models: ['meta-llama/Llama-3.3-70B-Instruct-Turbo', 'deepseek-ai/DeepSeek-V3.1', 'Qwen/Qwen2.5-72B-Instruct-Turbo', 'openai/gpt-oss-120b'] },
  { id: 'huggingface',  name: 'HuggingFace',          models: ['meta-llama/Llama-3.3-70B-Instruct', 'Qwen/Qwen2.5-72B-Instruct', 'deepseek-ai/DeepSeek-V3.1', 'openai/gpt-oss-120b'] },
  { id: 'fireworks',    name: 'Fireworks AI',         models: ['accounts/fireworks/models/llama-v3p1-70b-instruct', 'accounts/fireworks/models/llama-v3p3-70b-instruct', 'accounts/fireworks/models/qwen2p5-72b-instruct', 'accounts/fireworks/models/mixtral-8x22b-instruct'] },
  { id: 'deepseek',     name: 'DeepSeek',             models: ['deepseek-chat', 'deepseek-reasoner', 'deepseek-coder'] },
  { id: 'xai',          name: 'xAI (Grok)',           models: ['grok-4.5', 'grok-4.3', 'grok-4.20-non-reasoning', 'grok-code-fast-1'] },
  { id: 'cerebras',     name: 'Cerebras',             models: ['gpt-oss-120b', 'qwen-3-32b', 'llama-3.3-70b', 'llama3.1-8b'] },
  { id: 'perplexity',   name: 'Perplexity',           models: ['sonar', 'sonar-pro', 'sonar-reasoning-pro', 'sonar-deep-research'] },
  { id: 'ollama',       name: 'Ollama (Local)',       models: [] },
  { id: 'llamacpp',     name: 'llama.cpp (Local)',    models: [] },
  { id: 'azure',        name: 'Azure OpenAI',         models: ['gpt-4o', 'gpt-4-turbo', 'gpt-35-turbo'] },
  { id: 'bedrock',      name: 'AWS Bedrock',          models: ['anthropic.claude-3-5-sonnet-20241022-v2:0', 'amazon.titan-text-express-v1', 'amazon.nova-pro-v1:0', 'meta.llama3-70b-instruct-v1:0', 'mistral.mistral-large-2402-v1:0'] },
  { id: 'nvidia',       name: 'NVIDIA NIM',           models: ['nvidia/nemotron-3-super-120b-a12b', 'nvidia/nemotron-3-ultra-550b-a55b', 'nvidia/nemotron-3.5-lightning-30b-a3b', 'moonshotai/kimi-k2.6', 'mistralai/mistral-large-4-1t-a52b', 'openai/gpt-oss-20b'] },
  { id: 'watsonx',      name: 'IBM watsonx.ai',       models: ['ibm/granite-4-h-small', 'meta-llama/llama-3-3-70b-instruct', 'meta-llama/llama-4-maverick-17b-128e-instruct-fp8', 'mistralai/mistral-medium-2505', 'openai/gpt-oss-120b'] },
  { id: 'typesafe',     name: 'TypeSafe (Jev)',       models: ['jev-1', 'jev-fast', 'jev-classifier'] },
  { id: 'mock',         name: 'Mock / Simulator',     models: ['mock-gpt-4', 'mock-claude'] },
]

export function useCatalogData() {
  const [providers, setProviders] = useState<ProviderOption[]>(DEFAULT_PROVIDERS)
  const [toolCategories, setToolCategories] = useState<ToolCategory[]>([])
  // Set when /api/tools fails, so the sidebar says so instead of looking like an empty catalog
  const [toolsError, setToolsError] = useState<string | null>(null)
  const [customMcpServers, setCustomMcpServers] = useState<CustomMcpRecord[]>([])
  const [customMcpModalOpen, setCustomMcpModalOpen] = useState(false)
  const [editingCustomMcp, setEditingCustomMcp] = useState<CustomMcpRecord | undefined>(undefined)
  const [connections, setConnections] = useState<ConnectionRecord[]>([])
  const [connectionModalOpen, setConnectionModalOpen] = useState(false)
  const [editingConnection, setEditingConnection] = useState<ConnectionRecord | undefined>(undefined)
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseRecord[]>([])
  const [knowledgeBaseModalOpen, setKnowledgeBaseModalOpen] = useState(false)
  const [editingKnowledgeBase, setEditingKnowledgeBase] = useState<KnowledgeBaseRecord | undefined>(undefined)
  const [skills, setSkills] = useState<SkillRecord[]>([])
  const [skillsModalOpen, setSkillsModalOpen] = useState(false)

  const fetchSkills = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/skills`)
      if (res.ok) setSkills(await res.json())
    } catch { /* backend not reachable */ }
  }, [])

  const fetchCustomMcpServers = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/custom-mcp`)
      if (res.ok) setCustomMcpServers(await res.json())
    } catch { /* backend not reachable */ }
  }, [])

  const fetchConnections = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/connections`)
      if (res.ok) setConnections(await res.json())
    } catch { /* backend not reachable */ }
  }, [])

  const fetchKnowledgeBases = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/knowledge-bases`)
      if (res.ok) setKnowledgeBases(await res.json())
    } catch { /* backend not reachable */ }
  }, [])

  const applyToolsResponse = useCallback(async (res: Response) => {
    if (!res.ok) {
      setToolsError(`The tool catalog failed to load (HTTP ${res.status}). Check the backend log.`)
      return
    }
    const d = await res.json()
    if (d.categories) {
      setToolCategories(d.categories)
      setToolCatalog(d.categories)
    }
    setToolsError(null)
  }, [])

  const fetchTools = useCallback(async () => {
    try {
      await applyToolsResponse(await fetch(`${API_BASE}/api/tools`))
    } catch { setToolsError('The backend is not reachable.') }
  }, [applyToolsResponse])

  /** Call once on boot — fetches models, apps list, and tools catalog. */
  const bootFetch = useCallback(async (
    onApps: (apps: AppRecord[]) => void,
  ) => {
    try {
      const [modelsRes, appsRes, toolsRes, loadersRes] = await Promise.all([
        fetch(`${API_BASE}/api/models`),
        fetch(`${API_BASE}/api/apps`),
        fetch(`${API_BASE}/api/tools`),
        fetch(`${API_BASE}/api/retrieval/loaders`),
      ])
      // Loader catalog first: loading an app resolves loader types against it
      if (loadersRes.ok) {
        const d = await loadersRes.json()
        if (Array.isArray(d.loaders)) setDocLoaderCatalog(d.loaders)
      }
      if (modelsRes.ok) {
        const d = await modelsRes.json()
        if (d.providers) setProviders(d.providers)
      }
      await applyToolsResponse(toolsRes)
      if (appsRes.ok) {
        const apps: AppRecord[] = await appsRes.json()
        onApps(apps)
      }
    } catch (e) {
      console.warn('Backend not reachable.', e)
      setToolsError('The backend is not reachable.')
    }
    fetchCustomMcpServers()
    fetchConnections()
    fetchKnowledgeBases()
    fetchSkills()
  }, [applyToolsResponse, fetchCustomMcpServers, fetchConnections, fetchKnowledgeBases, fetchSkills])

  return {
    providers, setProviders,
    toolCategories,
    toolsError,
    fetchTools,
    customMcpServers, setCustomMcpServers,
    customMcpModalOpen, setCustomMcpModalOpen,
    editingCustomMcp, setEditingCustomMcp,
    connections, setConnections,
    connectionModalOpen, setConnectionModalOpen,
    editingConnection, setEditingConnection,
    knowledgeBases, setKnowledgeBases,
    knowledgeBaseModalOpen, setKnowledgeBaseModalOpen,
    editingKnowledgeBase, setEditingKnowledgeBase,
    skills, setSkills,
    skillsModalOpen, setSkillsModalOpen,
    fetchSkills,
    fetchCustomMcpServers,
    fetchConnections,
    fetchKnowledgeBases,
    bootFetch,
  }
}
