import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../../test/fetchStub'
import { ToolPackagesPanel } from './ToolPackagesPanel'

const tool = (id: string, name: string, category: string, type: 'tool' | 'mcp' = 'tool') =>
  ({ id, name, type, icon: '🔧', description: `${name} does things`, category, default_config: {} })

const catalog = {
  categories: [
    { id: 'agentic_tools', name: 'Tools', tools: [
      tool('calculator', 'Calculator', 'Everyday Utilities'),
      tool('snowflake_catalog', 'Snowflake Catalog', 'Data & Files'),
      tool('databricks_genie', 'Databricks Genie', 'Data & Files'),
    ] },
    { id: 'mcp_servers', name: 'MCP', tools: [tool('mcp_databricks', 'MCP Databricks', 'Databases & Data', 'mcp')] },
    { id: 'frameworks', name: 'Frameworks', tools: [tool('crewai', 'CrewAI', '')] },
  ],
}

const state = (id: string, installed: boolean, source: string | null = null, inUse = false) =>
  ({ id, installed, source, in_use: inUse, default: source === 'default' })

const packages = (canEdit = true) => ({
  can_edit: canEdit,
  packages: [
    state('calculator', true, 'default'),
    state('snowflake_catalog', false),
    state('databricks_genie', true, 'in_use', true),
    state('mcp_databricks', false),
  ],
})

describe('ToolPackagesPanel', () => {
  it('lists tools by category with their install state, MCP servers on their own tab', async () => {
    stubFetch({ 'GET /api/tools': catalog, 'GET /api/tools/packages': packages() })
    render(<ToolPackagesPanel />)
    expect(await screen.findByText('2 of 3 tools installed')).toBeTruthy()
    expect(screen.queryByText('Calculator')).toBeNull()
    expect(screen.getByText('1 / 2 installed')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(screen.getByText('Calculator')).toBeTruthy()
    expect(screen.getByText('Default')).toBeTruthy()
    expect(screen.getByText('Used in a pipeline')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Install Snowflake Catalog' })).toBeTruthy()
    expect(screen.queryByText('MCP Databricks')).toBeNull()
    expect(screen.queryByText('CrewAI')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'MCP servers' }))
    fireEvent.click(screen.getByRole('button', { name: /Databases & Data/ }))
    expect(screen.getByText('MCP Databricks')).toBeTruthy()
    expect(screen.getByText('0 of 1 MCP servers installed')).toBeTruthy()
  })

  it('installs a package and tells the app to reload the catalog', async () => {
    const fetchMock = stubFetch({
      'GET /api/tools': catalog,
      'GET /api/tools/packages': packages(),
      'PUT /api/tools/packages': { packages: [state('snowflake_catalog', true, 'choice')] },
    })
    const onChanged = vi.fn()
    render(<ToolPackagesPanel onChanged={onChanged} />)
    fireEvent.click(await screen.findByRole('button', { name: /Data & Files/ }))
    expect(screen.queryByText('Calculator')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Install Snowflake Catalog' }))
    expect(await screen.findByRole('button', { name: 'Uninstall Snowflake Catalog' })).toBeTruthy()
    expect(sentBody(fetchMock, 'PUT /api/tools/packages')).toEqual({ tool_ids: ['snowflake_catalog'], installed: true })
    expect(onChanged).toHaveBeenCalledTimes(1)
    expect(screen.getByText('3 of 3 tools installed')).toBeTruthy()
  })

  it('filters by search and installs everything shown', async () => {
    const fetchMock = stubFetch({
      'GET /api/tools': catalog,
      'GET /api/tools/packages': packages(),
      'PUT /api/tools/packages': { packages: [state('snowflake_catalog', true, 'choice')] },
    })
    render(<ToolPackagesPanel />)
    fireEvent.change(await screen.findByLabelText('Search packages'), { target: { value: 'snowflake' } })
    expect(screen.queryByText('Calculator')).toBeNull()
    expect(screen.getByText('Snowflake Catalog')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Expand all' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Install all 1 matching' }))
    await waitFor(() => expect(sentBody(fetchMock, 'PUT /api/tools/packages').tool_ids).toEqual(['snowflake_catalog']))
  })

  it('points a search with no match here to the other tab', async () => {
    stubFetch({ 'GET /api/tools': catalog, 'GET /api/tools/packages': packages() })
    render(<ToolPackagesPanel />)
    await screen.findByText('2 of 3 tools installed')
    fireEvent.change(screen.getByLabelText('Search packages'), { target: { value: 'MCP Databr' } })
    expect(screen.getByText(/No tools match “MCP Databr”\. 1 MCP server matches/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'MCP servers (1)' })).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'show MCP servers' }))
    expect(await screen.findByText('MCP Databricks')).toBeTruthy()
  })

  it('is read-only without write access', async () => {
    stubFetch({ 'GET /api/tools': catalog, 'GET /api/tools/packages': packages(false) })
    render(<ToolPackagesPanel />)
    expect(await screen.findByText(/installing them needs write access/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(screen.queryByRole('button', { name: /^Install / })).toBeNull()
    expect(screen.queryByText('Reset to defaults')).toBeNull()
  })

  it('reloads tools from disk for a server admin and refreshes the catalog', async () => {
    const fetchMock = stubFetch({
      'GET /api/tools': catalog,
      'GET /api/tools/packages': { ...packages(), can_reload: true },
      'POST /api/tools/reload': {
        changed: true, modules: 2, added: ['gitlab_api'], removed: [],
        errors: [{ module: 'tools.data.broken', error: 'SyntaxError: invalid syntax' }],
      },
    })
    const onChanged = vi.fn()
    render(<ToolPackagesPanel onChanged={onChanged} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Reload from disk' }))
    expect(await screen.findByText('Reloaded 2 modules · new: gitlab_api.')).toBeTruthy()
    expect(screen.getByText('tools.data.broken')).toBeTruthy()
    expect(onChanged).toHaveBeenCalledTimes(1)
    const listings = fetchMock.mock.calls.filter(([u, init]) => !init?.method && new URL(String(u)).pathname === '/api/tools/packages')
    expect(listings.length).toBe(2)
  })

  it('says when nothing changed, and hides the button from everyone else', async () => {
    stubFetch({
      'GET /api/tools': catalog,
      'GET /api/tools/packages': { ...packages(), can_reload: true },
      'POST /api/tools/reload': { changed: false, modules: 0, added: [], removed: [], errors: [] },
    })
    const onChanged = vi.fn()
    const { unmount } = render(<ToolPackagesPanel onChanged={onChanged} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Reload from disk' }))
    expect(await screen.findByText('No changes on disk since the last load.')).toBeTruthy()
    expect(onChanged).not.toHaveBeenCalled()
    unmount()

    stubFetch({ 'GET /api/tools': catalog, 'GET /api/tools/packages': packages() })
    render(<ToolPackagesPanel />)
    await screen.findByText('2 of 3 tools installed')
    expect(screen.queryByRole('button', { name: 'Reload from disk' })).toBeNull()
  })
})
