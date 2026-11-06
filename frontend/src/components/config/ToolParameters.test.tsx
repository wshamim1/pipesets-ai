import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../../test/fetchStub'
import { setToolCatalog } from '../../utils/toolCatalog'
import { McpToolsPicker, ToolParametersInfo } from './ToolParameters'

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('ToolParametersInfo', () => {
  it('lists what the model calls a built-in tool with', () => {
    setToolCatalog([{ id: 'c', name: 'Search', tools: [{
      id: 'web_search', name: 'Web Search', type: 'tool', icon: '🔍', description: '', default_config: {},
      parameters: { required: ['query'], properties: { query: { type: 'string', description: 'What to search for' },
                                                       max_results: { type: 'integer' } } },
    }] } as any])
    render(<ToolParametersInfo toolId="web_search" />)
    expect(screen.getByText('query: string (required) — What to search for')).toBeTruthy()
    expect(screen.getByText('max_results: integer')).toBeTruthy()
  })

  it('shows nothing for a tool without parameters', () => {
    const { container } = render(<ToolParametersInfo toolId="unknown_tool" />)
    expect(container.innerHTML).toBe('')
  })
})

describe('McpToolsPicker', () => {
  it('discovers a server’s tools and stores the picked ones with their schemas', async () => {
    const fetch = stubFetch({
      'POST /api/tools/discover': () => ({ tools: [
        { name: 'read_file', description: 'Read a file', inputSchema: { required: ['path'], properties: { path: { type: 'string' } } } },
        { name: 'list_dir', inputSchema: {} }] }),
    })
    const onChange = vi.fn()
    render(<McpToolsPicker toolId="mcp_filesystem" config={{ root: '/data' }} onChange={onChange} />)
    expect(screen.getByText(/None picked: the model sends one input string/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '🔍 Discover tools' }))
    fireEvent.click(await screen.findByRole('checkbox', { name: /read_file/ }))
    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ name: 'read_file' })])
    expect(sentBody(fetch, 'POST /api/tools/discover')).toEqual({ tool_type: 'mcp_filesystem', config: { root: '/data' } })
  })

  it('unpicking the last tool goes back to one input string', () => {
    const onChange = vi.fn()
    render(<McpToolsPicker toolId="mcp_fetch" config={{ mcp_tools: [{ name: 'fetch', inputSchema: {} }] }} onChange={onChange} />)
    expect(screen.getByText('1 tool, each called with its own arguments.')).toBeTruthy()
    fireEvent.click(screen.getByRole('checkbox', { name: /fetch/ }))
    expect(onChange).toHaveBeenCalledWith(undefined)
  })

  it('reports a server that won’t start', async () => {
    stubFetch({ 'POST /api/tools/discover': () => new Response(JSON.stringify({ detail: 'npx not found' }), { status: 502 }) })
    render(<McpToolsPicker toolId="mcp_git" config={{}} onChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: '🔍 Discover tools' }))
    expect((await screen.findByRole('alert')).textContent).toBe('npx not found')
  })
})
