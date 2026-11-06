import { fireEvent, render, screen } from '@testing-library/react'
import type { ComponentType } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '../../test/fetchStub'
import type { FlowNode, ProviderOption } from '../../types'
import { setDocLoaderCatalog } from '../../utils/docLoaders'
import { refreshSecrets } from '../../utils/secrets'
import { CacheConfigPanel } from './CacheConfigPanel'
import { ChildAgentConfigPanel } from './ChildAgentConfigPanel'
import { ConnectionConfigPanel } from './ConnectionConfigPanel'
import { DocLoaderConfigPanel } from './DocLoaderConfigPanel'
import { EmbeddingConfigPanel } from './EmbeddingConfigPanel'
import { GatewayConfigPanel } from './GatewayConfigPanel'
import { HumanGateConfigPanel } from './HumanGateConfigPanel'
import { CheckpointerConfigPanel } from './CheckpointerConfigPanel'
import { KnowledgeBaseConfigPanel } from './KnowledgeBaseConfigPanel'
import { LlmConfigPanel } from './LlmConfigPanel'
import { MasterAgentConfigPanel } from './MasterAgentConfigPanel'
import { MemoryConfigPanel } from './MemoryConfigPanel'
import { MiddlewareConfigPanel } from './MiddlewareConfigPanel'
import { OutputParserConfigPanel } from './OutputParserConfigPanel'
import { RerankerConfigPanel } from './RerankerConfigPanel'
import { RetrieverConfigPanel } from './RetrieverConfigPanel'
import { SkillConfigPanel } from './SkillConfigPanel'
import { SyntheticDataConfigPanel } from './SyntheticDataConfigPanel'
import { TextSplitterConfigPanel } from './TextSplitterConfigPanel'
import { ToolConfigPanel } from './ToolConfigPanel'
import { ToolkitConfigPanel } from './ToolkitConfigPanel'
import { VectorStoreConfigPanel } from './VectorStoreConfigPanel'
import { WorkflowStepConfigPanel } from './WorkflowStepConfigPanel'

/**
 * The contract every node config panel keeps, checked on the data a freshly dropped node gets
 * (copied from App.tsx's onDrop): it renders, label edits go through onUpdate, Save / Delete
 * call back — and on a published pipeline (readOnly) every field and action is disabled or gone.
 */

// The Skill panel has no Save / Delete of its own
const NO_ACTIONS = new Set(['Skill'])

const providers: ProviderOption[] = [
  { id: 'openai', name: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini'] },
  { id: 'mock', name: 'Mock', models: ['mock-gpt-4'] },
]

const agentLlm = {
  provider: 'openai', model: 'gpt-4o', api_key: '', timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
  fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '', base_url: '',
}

type Panel = ComponentType<any>
const PANELS: [name: string, Panel, type: string, data: Record<string, unknown>, extra?: Record<string, unknown>][] = [
  ['LLM', LlmConfigPanel, 'llm', {
    label: 'GPT-4O Node', temperature: 0.7, max_tokens: 1024, top_p: 1.0, system_prompt: 'Be concise.', ...agentLlm,
  }, { providers }],
  ['Tool', ToolConfigPanel, 'tool', {
    label: 'Calculator', toolId: 'calculator', toolType: 'builtin', icon: '🧮', description: '', config: {},
  }, { nodes: [], edges: [] }],
  ['Toolkit', ToolkitConfigPanel, 'toolkit', {
    label: 'My Toolkit', toolkitId: 'tk', icon: '🗂️', description: 'A custom toolkit.', subTools: [],
  }, { toolCategories: [], customTools: [] }],
  ['Memory', MemoryConfigPanel, 'memory', {
    label: 'Sliding Window Memory', strategy: 'sliding_window', token_budget: 4096, session_id: 'session-n1', session_ttl_hours: 24,
  }],
  ['Cache', CacheConfigPanel, 'cache', { label: 'Prompt Cache', scope: 'prompt', ttl_seconds: 3600, max_size: 500 }],
  ['Doc loader', DocLoaderConfigPanel, 'doc_loader', {
    label: 'PDF Loader', loader_type: 'pdf', source: '', chunk_strategy: 'fixed',
  }, { nodes: [], edges: [] }],
  ['Text splitter', TextSplitterConfigPanel, 'text_splitter', {
    label: 'Recursive Splitter', splitter_type: 'recursive_character', chunk_size: 512, chunk_overlap: 50,
  }],
  ['Embedding', EmbeddingConfigPanel, 'embedding', {
    label: 'OpenAI Embedding', provider: 'openai', model: 'text-embedding-3-small', api_key: '',
  }],
  ['Vector store', VectorStoreConfigPanel, 'vector_store', {
    label: 'Local Vector Store', store_type: 'local', collection_name: 'my_documents', connection_string: '', top_k: 5,
  }],
  ['Retriever', RetrieverConfigPanel, 'retriever', {
    label: 'Similarity Retriever', search_type: 'similarity', collection_name: 'my_documents', top_k: 5,
    score_threshold: 0, rerank: false, embedding_provider: 'local',
    embedding_model: 'sentence-transformers/all-MiniLM-L6-v2', embedding_api_key: '',
  }],
  ['Master agent', MasterAgentConfigPanel, 'master_agent', {
    label: 'Master Agent', ...agentLlm, goal: '', max_steps: 5, strategy: 'sequential',
  }],
  ['Child agent', ChildAgentConfigPanel, 'child_agent', {
    label: 'Researcher Agent', master_id: '', role: 'Researcher', ...agentLlm, allowed_tool_ids: [],
    system_prompt: 'You are a specialist Researcher.',
  }],
  ['Pipeline agent', ChildAgentConfigPanel, 'child_agent', {
    label: 'Pipeline Agent', master_id: '', role: 'Pipeline', ...agentLlm, timeout_ms: 120000, allowed_tool_ids: [],
    system_prompt: '', kind: 'pipeline', app_id: '', app_name: '', app_version: 0,
  }],
  ['External agent', ChildAgentConfigPanel, 'child_agent', {
    label: 'External Agent', master_id: '', role: 'Researcher', ...agentLlm, model: '', allowed_tool_ids: [],
    system_prompt: '', kind: 'external', endpoint_url: '', protocol: 'openai', auth_type: 'bearer',
    auth_header: 'X-API-Key', request_template: '', response_path: '',
  }],
  ['Connection', ConnectionConfigPanel, 'connection', {
    label: 'Prod DB', connection_id: 'c1', connection_type: 'postgres', icon: '🐘', description: '',
    config: { host: 'db', port: 5432 }, status: 'connected', status_msg: '',
  }],
  ['Knowledge base', KnowledgeBaseConfigPanel, 'knowledge_base', {
    label: 'Handbook', kb_id: 'kb1', icon: '📚', description: '', chunk_count: 10,
    embedding_provider: 'local', embedding_model: 'all-MiniLM-L6-v2', top_k: 4, score_threshold: 0,
  }],
  ['Skill', SkillConfigPanel, 'skill', {
    label: 'Summarize', skill_id: 's1', icon: '⚡', description: '', instructions: 'Summarize.',
    category: 'general', tool_ids: [], tags: [],
  }],
  ['Gateway', GatewayConfigPanel, 'gateway', {
    label: 'Condition Gateway', kind: 'condition', condition_expr: '', true_label: 'Yes', false_label: 'No',
  }],
  ['Loop gateway', GatewayConfigPanel, 'gateway', {
    label: 'Loop Gateway', kind: 'loop', max_iterations: 3, loop_condition: '',
  }],
  ['Reranker', RerankerConfigPanel, 'reranker', {
    label: 'Cohere Reranker', reranker_type: 'cohere', model: 'rerank-english-v3.0', api_key: '', top_n: 5,
  }],
  ['Human gate', HumanGateConfigPanel, 'human_gate', {
    label: 'Approval Gate', gate_type: 'approval', prompt_message: '', timeout_hours: 24, on_timeout: 'reject',
  }],
  ['Checkpointer', CheckpointerConfigPanel, 'checkpointer', {
    label: 'Checkpointer', save_steps: true, restore_on_resume: true,
  }],
  ['Workflow step', WorkflowStepConfigPanel, 'wf_step', {
    label: 'Ask User', step_type: 'ask', prompt: '', variable: '', input_kind: 'text',
    options_source: '', option_label_field: '', option_value_field: '', tool_id: '', tool_input: '',
  }, { nodes: [], edges: [] }],
  ['Output parser', OutputParserConfigPanel, 'output_parser', {
    label: 'JSON Parser', parser_type: 'json', schema_json: '', strict: false,
  }],
  ['Middleware', MiddlewareConfigPanel, 'middleware', {
    label: 'Content Moderation', middleware_type: 'content_moderation', config: {}, enabled: true,
  }],
  ['Rate limiter', MiddlewareConfigPanel, 'middleware', {
    label: 'Rate Limiter', middleware_type: 'rate_limiter', config: { per: 'caller' }, enabled: true,
  }],
  ['Synthetic data', SyntheticDataConfigPanel, 'synthetic_data', {
    label: 'Synthetic Data Generator',
    dataset_name: 'synthetic_dataset',
    row_count: 100,
    output_format: 'jsonl',
    schema_mode: 'manual',
    schema_json: '',
    columns: [{ id: 'c1', name: 'customer_id', type: 'uuid', nullable: false, unique: true }],
    locale: 'en_US',
    seed: 42,
    strict_schema: true,
    include_edge_cases: true,
    prompt_instructions: '',
  }],
]

function renderPanel(Component: Panel, type: string, data: Record<string, unknown>, extra = {}, readOnly = false) {
  const activeNode = { id: 'n1', type, position: { x: 0, y: 0 }, data } as unknown as FlowNode
  const props = { onUpdate: vi.fn(), onDelete: vi.fn(), onSave: vi.fn() }
  const view = render(<Component activeNode={activeNode} {...props} readOnly={readOnly} {...extra} />)
  return { ...view, ...props }
}

beforeEach(async () => {
  // Panels that load stats / sessions / versions get an empty answer
  stubFetch({ 'GET /api/secrets': [], '*': {} })
  await refreshSecrets()
  setDocLoaderCatalog([{ type: 'pdf', label: 'PDF', icon: '📄', desc: '', sourceLabel: 'File', placeholder: '', available: true }])
})

describe.each(PANELS)('%s config panel', (name, Component, type, data, extra) => {
  it('edits the label and calls Save / Delete', () => {
    const { onUpdate, onSave, onDelete } = renderPanel(Component, type, data, extra)
    fireEvent.change(screen.getByDisplayValue(String(data.label)), { target: { value: 'Renamed' } })
    expect(onUpdate).toHaveBeenCalledWith('n1', expect.objectContaining({ label: 'Renamed' }))
    if (NO_ACTIONS.has(name)) return

    fireEvent.click(screen.getByRole('button', { name: /save to app/i }))
    expect(onSave).toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /delete node/i }))
    expect(onDelete).toHaveBeenCalledWith('n1')
  })

  it('is fully read-only on a published pipeline', () => {
    const { container, onUpdate } = renderPanel(Component, type, data, extra, true)
    const enabled = [...container.querySelectorAll<HTMLInputElement>('input, select, textarea')]
      .filter((el) => !el.disabled && !el.readOnly)
      .map((el) => el.outerHTML.slice(0, 120))
    expect(enabled).toEqual([])
    const actions = screen.queryAllByRole('button', { name: /save to app|delete node/i })
    expect(actions.filter((b) => !(b as HTMLButtonElement).disabled)).toEqual([])
    expect(onUpdate).not.toHaveBeenCalled()
  })
})

describe('Doc loader OCR settings', () => {
  const pdf = { label: 'PDF Loader', loader_type: 'pdf', source: '', chunk_strategy: 'fixed' }

  it('offers OCR engines for loaders that meet scans, and the vision model when picked', () => {
    const { onUpdate, rerender } = renderPanel(DocLoaderConfigPanel, 'doc_loader', pdf, { nodes: [], edges: [] })
    fireEvent.change(screen.getByDisplayValue(/Auto — first installed/), { target: { value: 'vision' } })
    expect(onUpdate).toHaveBeenCalledWith('n1', { ocr_engine: 'vision' })
    expect(screen.getByPlaceholderText('eng')).toBeTruthy()

    const node = (data: Record<string, unknown>) =>
      ({ id: 'n1', type: 'doc_loader', position: { x: 0, y: 0 }, data }) as unknown as FlowNode
    const props = { nodes: [], edges: [], onUpdate, onDelete: vi.fn(), onSave: vi.fn() }
    rerender(<DocLoaderConfigPanel activeNode={node({ ...pdf, ocr_engine: 'vision' })} {...props} />)
    fireEvent.change(screen.getByPlaceholderText('gpt-4o-mini'), { target: { value: 'claude-haiku' } })
    expect(onUpdate).toHaveBeenCalledWith('n1', { ocr_model: 'claude-haiku' })
    expect(screen.queryByPlaceholderText('eng')).toBeNull()

    rerender(<DocLoaderConfigPanel activeNode={node({ ...pdf, loader_type: 'csv' })} {...props} />)
    expect(screen.queryByText('Scanned pages (OCR)')).toBeNull()
  })
})
