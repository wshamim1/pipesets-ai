import { beforeEach, describe, expect, it } from 'vitest'
import type { FlowEdge, FlowNode } from '../types'
import { setDocLoaderCatalog, type DocLoaderDef } from './docLoaders'
import { validatePipeline, type ValidationIssue } from './pipelineValidation'

const node = (id: string, type: string, data: Record<string, unknown> = {}): FlowNode =>
  ({ id, type, position: { x: 0, y: 0 }, data: { label: id, ...data } }) as unknown as FlowNode
const edge = (source: string, target: string): FlowEdge =>
  ({ id: `${source}-${target}`, source, target }) as FlowEdge

type KeyResolver = (provider: string, nodeKey?: string) => string
type RequiredConfig = (toolId: string) => string[]

const noKeys: KeyResolver = () => ''
const allKeys: KeyResolver = () => 'sk-test'
const noRequired: RequiredConfig = () => []

const ids = (issues: ValidationIssue[]) => issues.map((i) => i.id)
const run = (nodes: FlowNode[], edges: FlowEdge[] = [], keys = allKeys, required = noRequired) =>
  validatePipeline(nodes, edges, keys, required)

const loader = (type: string, extra: Partial<DocLoaderDef> = {}): DocLoaderDef =>
  ({ type, label: type, icon: '', desc: '', sourceLabel: 'Source', placeholder: '', available: true, ...extra })

/** start → llm → stop, a mock model: the smallest pipeline with no issues. */
const wired = (llmData: Record<string, unknown> = { provider: 'mock' }) => ({
  nodes: [node('start', 'start'), node('llm', 'llm', llmData), node('stop', 'stop')],
  edges: [edge('start', 'llm'), edge('llm', 'stop')],
})

beforeEach(() => {
  setDocLoaderCatalog([
    loader('pdf'),
    loader('postgres', { usesConnection: true }),
    loader('notion', { label: 'Notion', available: false }),
  ])
})

describe('validatePipeline', () => {
  it('passes a wired start → llm → stop pipeline', () => {
    const { nodes, edges } = wired()
    expect(run(nodes, edges)).toEqual([])
  })

  it('errors on an empty canvas and warns about missing start / stop', () => {
    const issues = run([])
    expect(ids(issues)).toEqual(['missing-runnable-node', 'missing-start-node', 'missing-stop-node'])
    expect(issues[0].severity).toBe('error')
    expect(issues.slice(1).every((i) => i.severity === 'warn')).toBe(true)
  })

  it('counts a pipeline child agent as runnable', () => {
    expect(ids(run([node('c', 'child_agent', { kind: 'pipeline', app_id: 'app-1' })])))
      .not.toContain('missing-runnable-node')
  })

  it('warns about unwired start / stop and isolated critical nodes', () => {
    const issues = run([node('start', 'start'), node('llm', 'llm', { provider: 'mock' }), node('stop', 'stop')])
    expect(ids(issues)).toEqual(['start-unwired-start', 'stop-unwired-stop', 'isolated-llm'])
    expect(issues.find((i) => i.id === 'isolated-llm')?.nodeId).toBe('llm')
  })

  it('requires an API key for hosted providers but not local ones', () => {
    const hosted = wired({ provider: 'openai' })
    expect(ids(run(hosted.nodes, hosted.edges, noKeys))).toEqual(['missing-key-llm'])
    expect(run(hosted.nodes, hosted.edges, allKeys)).toEqual([])
    for (const provider of ['mock', 'ollama', 'llamacpp', 'jan', 'local']) {
      const local = wired({ provider })
      expect(run(local.nodes, local.edges, noKeys)).toEqual([])
    }
  })

  it('passes the node key to the resolver', () => {
    const { nodes, edges } = wired({ provider: 'openai', api_key: 'secret://abc' })
    const seen: [string, string | undefined][] = []
    run(nodes, edges, (p, k) => { seen.push([p, k]); return 'resolved' })
    expect(seen).toEqual([['openai', 'secret://abc']])
  })

  it('checks LLM timeout, retry and backoff ranges', () => {
    const { nodes, edges } = wired({ provider: 'mock', timeout_ms: 500, max_retries: 6, retry_backoff_ms: -1 })
    expect(ids(run(nodes, edges))).toEqual(['invalid-timeout-llm', 'invalid-retries-llm', 'invalid-backoff-llm'])
  })

  it('checks the fallback model and its key', () => {
    const noModel = wired({ provider: 'mock', fallback_provider: 'anthropic' })
    expect(ids(run(noModel.nodes, noModel.edges))).toEqual(['fallback-model-missing-llm'])

    const noKey = wired({ provider: 'mock', fallback_provider: 'anthropic', fallback_model: 'claude' })
    expect(ids(run(noKey.nodes, noKey.edges, noKeys))).toEqual(['fallback-key-missing-llm'])

    const mock = wired({ provider: 'mock', fallback_provider: 'mock', fallback_model: 'mock' })
    expect(ids(run(mock.nodes, mock.edges))).toEqual(['fallback-mock-unsupported-llm'])
  })

  it('validates child agents by kind', () => {
    const base = wired()
    const children = [
      node('p', 'child_agent', { kind: 'pipeline', app_id: '' }),
      node('x', 'child_agent', { kind: 'external', endpoint_url: 'not a url' }),
      node('ok', 'child_agent', { kind: 'external', endpoint_url: 'https://agent.example', auth_type: 'none' }),
    ]
    const edges = [...base.edges, ...children.map((c) => edge('llm', c.id))]
    expect(ids(run([...base.nodes, ...children], edges)))
      .toEqual(['pipeline-child-unset-p', 'external-endpoint-x', 'external-auth-x'])
  })

  it('names the missing required tool config', () => {
    const base = wired()
    const tool = node('t', 'tool', { label: 'Serper', toolId: 'serper', config: { api_key: ' ' } })
    const issues = run([...base.nodes, tool], base.edges, allKeys, (id) => (id === 'serper' ? ['api_key'] : []))
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({ id: 'tool-config-missing-t', severity: 'error', title: 'Serper needs api_key' })
  })

  it('flags a wired connection that failed its health check, not an unwired one', () => {
    const base = wired()
    const conn = node('c', 'connection', { status: 'error', status_msg: 'refused' })
    expect(run([...base.nodes, conn], base.edges)).toEqual([])
    const issues = run([...base.nodes, conn], [...base.edges, edge('c', 'llm')])
    expect(issues).toEqual([expect.objectContaining({ id: 'connection-error-c', hint: 'refused' })])
  })

  it('validates document loaders by catalog entry', () => {
    const base = wired()
    const loaders = [
      node('soon', 'doc_loader', { loader_type: 'notion' }),
      node('db', 'doc_loader', { loader_type: 'postgres' }),
      node('file', 'doc_loader', { loader_type: 'pdf', source: '' }),
    ]
    const edges = [...base.edges, ...loaders.map((l) => edge(l.id, 'llm'))]
    expect(ids(run([...base.nodes, ...loaders], edges)))
      .toEqual(['loader-unavailable-soon', 'loader-connection-db', 'loader-source-file'])

    const conn = node('conn', 'connection')
    expect(ids(run([...base.nodes, ...loaders, conn], [...edges, edge('conn', 'db')])))
      .not.toContain('loader-connection-db')
  })

  it('requires a collection on vector stores and retrievers', () => {
    const base = wired()
    const store = node('vs', 'vector_store', { collection_name: '' })
    const retriever = node('r', 'retriever', { collection_name: ' ', embedding_provider: 'openai' })
    const edges = [...base.edges, edge('vs', 'llm'), edge('r', 'llm')]
    expect(ids(run([...base.nodes, store, retriever], edges, noKeys)))
      .toEqual(['missing-key-r', 'vector-collection-vs', 'retriever-collection-r'])
  })
})
