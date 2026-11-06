import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { json, stubFetch } from '../test/fetchStub'
import { getToolSpec, requiredConfigFor } from '../utils/toolCatalog'
import { useCatalogData } from './useCatalogData'

const lists = { 'GET /api/custom-mcp': [], 'GET /api/connections': [], 'GET /api/knowledge-bases': [], 'GET /api/skills': [] }

describe('useCatalogData.bootFetch', () => {
  it('loads providers, tools and apps from the backend', async () => {
    stubFetch({
      ...lists,
      'GET /api/models': { providers: [{ id: 'mock', name: 'Mock', models: ['m1'] }] },
      'GET /api/apps': [{ id: 'a1' }],
      'GET /api/tools': { categories: [{ id: 'web', label: 'Web', tools: [{ id: 'boot_test_tool', name: 'T', required_config: ['api_key'] }] }] },
      'GET /api/retrieval/loaders': { loaders: [] },
      'GET /api/skills': [{ id: 's1', name: 'Skill' }],
    })
    const onApps = vi.fn()
    const { result } = renderHook(() => useCatalogData())
    await act(() => result.current.bootFetch(onApps))
    await act(async () => {})  // the follow-up list fetches aren't awaited by bootFetch

    expect(result.current.providers.map((p) => p.id)).toEqual(['mock'])
    expect(result.current.toolCategories).toHaveLength(1)
    expect(getToolSpec('boot_test_tool')).toBeDefined()
    expect(requiredConfigFor('boot_test_tool')).toEqual(['api_key'])
    expect(onApps).toHaveBeenCalledWith([{ id: 'a1' }])
    expect(result.current.skills).toEqual([{ id: 's1', name: 'Skill' }])
  })

  it('keeps the built-in provider list when the backend is down', async () => {
    stubFetch({})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const onApps = vi.fn()
    const { result } = renderHook(() => useCatalogData())
    await act(() => result.current.bootFetch(onApps))

    expect(result.current.providers.map((p) => p.id)).toContain('openai')
    expect(onApps).not.toHaveBeenCalled()
  })

  it('reports a failed tool catalog instead of showing it as empty, and retries', async () => {
    const tools = { categories: [{ id: 'web', label: 'Web', tools: [] }] }
    let toolsRoute: unknown = json({ detail: 'Internal Server Error' }, 500)
    stubFetch({
      ...lists,
      'GET /api/models': { providers: [] },
      'GET /api/apps': [],
      'GET /api/tools': () => toolsRoute,
      'GET /api/retrieval/loaders': { loaders: [] },
    })
    const { result } = renderHook(() => useCatalogData())
    await act(() => result.current.bootFetch(vi.fn()))
    await act(async () => {})

    expect(result.current.toolsError).toMatch(/HTTP 500/)
    expect(result.current.toolCategories).toEqual([])

    toolsRoute = tools
    await act(() => result.current.fetchTools())
    expect(result.current.toolsError).toBeNull()
    expect(result.current.toolCategories).toHaveLength(1)
  })

  it('reports an unreachable backend as a tool catalog error', async () => {
    stubFetch({})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { result } = renderHook(() => useCatalogData())
    await act(() => result.current.bootFetch(vi.fn()))

    expect(result.current.toolsError).toMatch(/not reachable/)
  })
})
