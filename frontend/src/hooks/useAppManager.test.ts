import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { json, sentBody, stubFetch } from '../test/fetchStub'
import type { AppRecord, FlowEdge, FlowNode } from '../types'
import { useAppManager } from './useAppManager'

const app = (extra: Partial<AppRecord> = {}): AppRecord =>
  ({ id: 'a1', name: 'App', description: '', status: 'draft', version: 1, created_at: '', updated_at: '',
     flow_data: { nodes: [], edges: [] }, ...extra }) as AppRecord

const conn = (id: string, connection_id: string): FlowNode =>
  ({ id, type: 'connection', position: { x: 0, y: 0 },
     data: { label: id, connection_id, config: { host: 'old' }, status: 'unknown' } }) as unknown as FlowNode

function setup(nodes: FlowNode[] = [], edges: FlowEdge[] = [], providerKeys: Record<string, string> = {}) {
  const loadFlow = vi.fn()
  const setNodes = vi.fn()
  const setEdges = vi.fn()
  const setSelectedNodeId = vi.fn()
  const hook = renderHook(() =>
    useAppManager(loadFlow, nodes, edges, setNodes, setEdges, setSelectedNodeId, () => providerKeys))
  return { ...hook, loadFlow, setNodes, setEdges }
}

/** Open an app without going through loadApp (and its connection refresh). */
const open = (r: ReturnType<typeof setup>['result'], a = app()) => act(() => r.current.setCurrentApp(a))

describe('useAppManager.loadApp', () => {
  it('refreshes connection nodes from /api/connections', async () => {
    stubFetch({ 'GET /api/connections': [{ id: 'c1', config: { host: 'new' }, status: 'ok', status_msg: 'up' }] })
    const { result, loadFlow } = setup()
    const nodes = [conn('n1', 'c1'), conn('n2', 'gone')]
    await act(() => result.current.loadApp(app({ flow_data: { nodes, edges: [] } })))

    const loaded: FlowNode[] = loadFlow.mock.calls[0][0].flow_data.nodes
    expect(loaded[0].data).toMatchObject({ config: { host: 'new' }, status: 'ok', status_msg: 'up' })
    expect(loaded[1]).toBe(nodes[1])
  })

  it('loads the app as saved when the API is down', async () => {
    stubFetch({})
    const { result, loadFlow } = setup()
    const a = app({ flow_data: { nodes: [conn('n1', 'c1')], edges: [] } })
    await act(() => result.current.loadApp(a))
    expect(loadFlow).toHaveBeenCalledWith(a)
  })
})

describe('useAppManager.saveCurrentApp', () => {
  it('sends the live canvas and stores the server copy', async () => {
    const nodes = [conn('n1', 'c1')]
    const fetch = stubFetch({ 'PUT /api/apps/a1': () => app({ version: 2 }) })
    const { result } = setup(nodes)
    open(result)
    await act(() => result.current.saveCurrentApp())

    expect(sentBody(fetch, 'PUT /api/apps/a1').flow_data).toEqual({ nodes: JSON.parse(JSON.stringify(nodes)), edges: [] })
    expect(result.current.currentApp?.version).toBe(2)
    expect(result.current.appSaveStatus).toBe('✓ Saved to SQLite')
  })

  it("shows the server's reason when it refuses the save", async () => {
    stubFetch({ 'PUT /api/apps/a1': () => json({ detail: { message: 'Key in plain text on node llm-1' } }, 400) })
    const { result } = setup()
    open(result)
    await act(() => result.current.saveCurrentApp())
    expect(result.current.appSaveStatus).toBe('✗ Key in plain text on node llm-1')
  })
})

describe('useAppManager.publishApp', () => {
  const gate = { status: 'failed', mode: 'block', reasons: ['pass rate 50% < 80%'], passed: 1, total: 2, pass_rate: 0.5 }

  it('saves first, sends provider keys, and reports the passed gate', async () => {
    const fetch = stubFetch({
      'PUT /api/apps/a1': () => app(),
      'POST /api/apps/a1/publish': () => ({ ...app({ version: 3 }), publish_gate: { ...gate, status: 'passed', passed: 2, pass_rate: 1 } }),
      'GET /api/apps': () => [],
    })
    const { result } = setup([], [], { openai: 'sk-browser' })
    open(result)
    await act(() => result.current.publishApp())

    expect(sentBody(fetch, 'POST /api/apps/a1/publish')).toEqual({ force: false, provider_keys: { openai: 'sk-browser' } })
    expect(result.current.appSaveStatus).toBe('✓ Published v3 · eval 2/2 passed (100%)')
  })

  it('does not publish when the save before it is refused', async () => {
    const fetch = stubFetch({ 'PUT /api/apps/a1': () => json({ detail: 'nope' }, 400) })
    const { result } = setup()
    open(result)
    await act(() => result.current.publishApp())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(result.current.appSaveStatus).toBe('✗ nope')
  })

  it('a failed gate blocks unless the user overrides, then publishes with force', async () => {
    const fetch = stubFetch({
      'PUT /api/apps/a1': () => app(),
      'POST /api/apps/a1/publish': (init?: RequestInit) => JSON.parse(String(init?.body)).force
        ? { ...app({ version: 3 }), publish_gate: { ...gate, status: 'overridden' } }
        : json({ detail: { gate } }, 409),
      'GET /api/apps': () => [],
    })
    const confirm = vi.fn((_message?: string) => false)
    vi.stubGlobal('confirm', confirm)
    const { result } = setup()
    open(result)

    await act(() => result.current.publishApp())
    expect(confirm.mock.calls[0][0]).toContain('pass rate 50% < 80%')
    expect(result.current.appSaveStatus).toBe('✗ Publish blocked by eval gate')

    confirm.mockReturnValue(true)
    await act(() => result.current.publishApp())
    expect(sentBody(fetch, 'POST /api/apps/a1/publish', 2).force).toBe(true)
    expect(result.current.appSaveStatus).toBe('✓ Published v3 · eval gate overridden')
  })

  it('a gate that could not run is never offered for override', async () => {
    stubFetch({
      'PUT /api/apps/a1': () => app(),
      'POST /api/apps/a1/publish': () =>
        json({ detail: { message: 'Dataset missing', gate: { status: 'error', mode: 'block', reasons: [] } } }, 409),
    })
    const confirm = vi.fn(() => true)
    vi.stubGlobal('confirm', confirm)
    const { result } = setup()
    open(result)
    await act(() => result.current.publishApp())
    expect(confirm).not.toHaveBeenCalled()
    expect(result.current.appSaveStatus).toBe('✗ Dataset missing')
  })
})

describe('useAppManager.deleteApp', () => {
  it('opens the next app after deleting the current one, or clears the canvas', async () => {
    stubFetch({ 'DELETE /api/apps/a1': () => ({}), 'DELETE /api/apps/a2': () => ({}), 'GET /api/connections': () => [] })
    const { result, loadFlow, setNodes } = setup()
    act(() => result.current.setSavedAppsList([app(), app({ id: 'a2', name: 'Second' })]))
    open(result)

    await act(async () => { await result.current.deleteApp('a1') })
    expect(result.current.savedAppsList.map((a) => a.id)).toEqual(['a2'])
    expect(loadFlow.mock.calls[0][0].id).toBe('a2')

    await act(async () => { await result.current.deleteApp('a2') })
    expect(result.current.currentApp).toBeNull()
    expect(setNodes).toHaveBeenCalledWith([])
  })
})
