import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../../test/fetchStub'
import { refreshAgentCatalog } from '../../utils/agentCatalog'
import { agent } from '../../test/agentFixtures'
import { AgentPackagesPanel } from './AgentPackagesPanel'

const sql = agent({
  id: 'sql_analyst', name: 'SQL Analyst', group: 'Data platform', role: 'SQL Analyst', starter: false,
  installed: false, source: null, ready: false, missing_tools: ['snowflake_catalog'],
  tools: [
    { ids: ['snowflake_reader', 'sql_database'], optional: false, why: 'runs queries', installed: 'sql_database', use: 'sql_database',
      names: { snowflake_reader: 'Snowflake Reader', sql_database: 'SQL Database' } },
    { ids: ['snowflake_catalog', 'databricks_unity_catalog'], optional: false, why: 'reads the schema', installed: null,
      use: 'snowflake_catalog', names: { snowflake_catalog: 'Snowflake Catalog', databricks_unity_catalog: 'Unity Catalog' } },
  ],
})
const catalog = (agents = [agent({}), sql], canEdit = true) =>
  ({ groups: ['Research & analysis', 'Data platform'], can_edit: canEdit, can_install_tools: canEdit, agents })

describe('AgentPackagesPanel', () => {
  beforeEach(() => { vi.unstubAllGlobals() })

  it('lists agents by group with install state and the tools they need', async () => {
    stubFetch({ 'GET /api/agent-catalog': catalog() })
    await refreshAgentCatalog()
    render(<AgentPackagesPanel />)
    expect(await screen.findByText('1 of 2 agents installed')).toBeTruthy()
    expect(screen.getByText('Default')).toBeTruthy()
    expect(screen.getByText('Needs 1 tool')).toBeTruthy()
    const needs = screen.getByRole('list', { name: 'Tools SQL Analyst needs' })
    expect(needs.textContent).toContain('✓SQL Database — runs queries')
    expect(needs.textContent).toContain('⚠Any of: Snowflake Catalog, Unity Catalog — reads the schema')
    expect(needs.textContent).not.toContain('sql_database')
    expect(screen.getByRole('button', { name: /Research & analysis/ }).textContent).toContain('1 / 1 installed')
    fireEvent.click(screen.getByRole('button', { name: /Data platform/ }))
    expect(screen.queryByText('SQL Analyst')).toBeNull()
    expect(screen.getByRole('button', { name: 'Uninstall Researcher' })).toBeTruthy()
  })

  it('installs an agent with its missing tools and tells the app the tools changed', async () => {
    const installed = { ...sql, installed: true, source: 'choice' as const, ready: true, missing_tools: [] }
    let after = false
    const fetchMock = stubFetch({
      'GET /api/agent-catalog': () => catalog(after ? [agent({}), installed] : undefined),
      'PUT /api/agent-catalog/packages': () => { after = true; return { agents: [installed], tools_installed: ['snowflake_catalog'] } },
    })
    await refreshAgentCatalog()
    const onToolsChanged = vi.fn()
    render(<AgentPackagesPanel onToolsChanged={onToolsChanged} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Install SQL Analyst with its tools' }))
    await waitFor(() => expect(screen.getByText('Installed SQL Analyst and its tools: snowflake_catalog.')).toBeTruthy())
    expect(sentBody(fetchMock, 'PUT /api/agent-catalog/packages')).toEqual({ agent_ids: ['sql_analyst'], installed: true, with_tools: true })
    expect(onToolsChanged).toHaveBeenCalled()
    expect(screen.getByText('2 of 2 agents installed')).toBeTruthy()
  })

  it('is read-only without write access', async () => {
    stubFetch({ 'GET /api/agent-catalog': catalog(undefined, false) })
    await refreshAgentCatalog()
    render(<AgentPackagesPanel />)
    expect(await screen.findByText(/installing them needs write access to agents/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^(Install|Uninstall) / })).toBeNull()
    expect(screen.getAllByText('Not installed')).toHaveLength(2)   // the filter and SQL Analyst's badge
  })
})
