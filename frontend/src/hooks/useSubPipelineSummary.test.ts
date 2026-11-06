import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../test/fetchStub'
import type { FlowNode } from '../types'
import { useSubPipelineSummary } from './useSubPipelineSummary'

const pipelineNode = (id: string, app_id: string, app_version = 1): FlowNode =>
  ({ id, type: 'child_agent', position: { x: 0, y: 0 },
     data: { label: id, kind: 'pipeline', app_id, app_version, app_name: `App ${app_id}` } }) as unknown as FlowNode
const llmNode = (id: string): FlowNode =>
  ({ id, type: 'llm', position: { x: 0, y: 0 }, data: { label: id } }) as unknown as FlowNode

const SUMMARY = { models: [], tools: [], memory: true, cache: false, pipelines: [], errors: [] }
const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(250) })

beforeEach(() => { vi.useFakeTimers() })

describe('useSubPipelineSummary', () => {
  it('is null and makes no request when no pipeline is called', async () => {
    const fetch = stubFetch({})
    const { result } = renderHook(() => useSubPipelineSummary([llmNode('a')]))
    await flush()
    expect(result.current).toBeNull()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('posts only the pipeline references, debounced', async () => {
    const fetch = stubFetch({ 'POST /api/pipelines/summary': SUMMARY })
    const { result } = renderHook(() => useSubPipelineSummary([llmNode('a'), pipelineNode('p', 'app-1', 3)], 'me'))
    expect(fetch).not.toHaveBeenCalled()
    await flush()

    expect(result.current).toEqual(SUMMARY)
    const body = sentBody(fetch, 'POST /api/pipelines/summary')
    expect(body.app_id).toBe('me')
    expect(body.flow_data.nodes).toEqual([
      { id: 'p', type: 'child_agent', data: { kind: 'pipeline', app_id: 'app-1', app_version: 3, app_name: 'App app-1' } },
    ])
  })

  it('refetches when a reference is re-pinned, not on unrelated edits', async () => {
    const fetch = stubFetch({ 'POST /api/pipelines/summary': () => SUMMARY })
    const { rerender } = renderHook(({ nodes }) => useSubPipelineSummary(nodes),
      { initialProps: { nodes: [pipelineNode('p', 'app-1', 1)] } })
    await flush()
    rerender({ nodes: [pipelineNode('p', 'app-1', 1), llmNode('new')] })
    await flush()
    expect(fetch).toHaveBeenCalledTimes(1)

    rerender({ nodes: [pipelineNode('p', 'app-1', 2)] })
    await flush()
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('falls back to null when the backend is unreachable', async () => {
    stubFetch({})
    const { result } = renderHook(() => useSubPipelineSummary([pipelineNode('p', 'app-1')]))
    await flush()
    expect(result.current).toBeNull()
  })
})
