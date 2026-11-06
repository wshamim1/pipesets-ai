import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { stubFetch } from '../test/fetchStub'
import { FRONTEND_BUILD } from '../utils/about'
import { AboutPanel } from './AboutPanel'
import { TopNav } from './TopNav'

const about = {
  app: { name: 'Pipesets AI', version: '0.7.0', license: 'Apache-2.0',
         commit: { short: '449fedb', hash: '449fedb0'.padEnd(40, '0'), date: '2026-11-04T16:56:11-05:00', subject: 'added release notes' } },
  backend: { python: '3.12.9', implementation: 'CPython', platform: 'Linux 6.8 (x86_64)', frozen: false,
             libraries: [{ name: 'FastAPI', version: '0.142.2', role: 'HTTP API' }],
             database: { type: 'postgresql', driver: 'psycopg', version: '16.4' }, llm_backends: ['anthropic', 'openai_compat'] },
  catalog: { tools: 189, mcp_servers: 106, frameworks: 8, agents: 27, starter_roles: 14, skills: 4 },
}

describe('About', () => {
  it('shows the version, commit, frontend and backend stacks, database and catalog', async () => {
    stubFetch({ 'GET /api/about': about })
    render(<AboutPanel onClose={vi.fn()} />)
    const version = await screen.findByRole('region', { name: 'Version' })
    expect(within(version).getByText('0.7.0')).toBeTruthy()
    expect(within(version).getByText('449fedb')).toBeTruthy()
    const backend = screen.getByRole('region', { name: 'Backend' })
    expect(backend.textContent).toContain('3.12.9')
    expect(backend.textContent).toContain('FastAPI0.142.2 · HTTP API')
    expect(backend.textContent).toContain('PostgreSQL 16.4 · psycopg')
    expect(screen.getByRole('region', { name: 'Built-in catalog' }).textContent).toContain('27 · plus 14 starter roles')
  })

  it('lists the libraries this bundle was built with, read at build time', () => {
    stubFetch({ 'GET /api/about': about })
    render(<AboutPanel onClose={vi.fn()} />)
    expect(FRONTEND_BUILD.libraries.map((l) => l.name)).toEqual(expect.arrayContaining(['React', 'React Flow', 'Vite']))
    const react = FRONTEND_BUILD.libraries.find((l) => l.name === 'React')!
    expect(react.version).toMatch(/^\d+\.\d+\.\d+/)
    expect(screen.getByRole('region', { name: 'Frontend' }).textContent).toContain(`React${react.version}`)
  })

  it('still shows the frontend when the backend is unreachable', async () => {
    stubFetch({})
    render(<AboutPanel onClose={vi.fn()} />)
    expect(await screen.findByText(/Couldn't reach the backend/)).toBeTruthy()
    expect(screen.getByRole('region', { name: 'Frontend' })).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Backend' })).toBeNull()
  })

  it('opens from the Help menu', async () => {
    stubFetch({ 'GET /api/about': about, 'GET /api/release-notes': { source: 'none', commits: [] } })
    render(<TopNav view="build" monitorTab="runs" automationTab="schedules" onViewChange={vi.fn()} onMonitorTabChange={vi.fn()}
      onAutomationTabChange={vi.fn()} onOpenSettings={vi.fn()} tenantId="t" tenants={[]} projectId="p" user={null}
      projects={[]} onTenantChange={vi.fn()} onProjectChange={vi.fn()} onLogout={vi.fn()} />)
    fireEvent.click(screen.getByTitle('Help — docs, shortcuts, report a bug'))
    fireEvent.click(screen.getByRole('menuitem', { name: 'About Pipesets' }))
    expect(await screen.findByRole('dialog', { name: 'About Pipesets AI' })).toBeTruthy()
  })

  it('opens the shortcuts list with "?" but not while typing', () => {
    stubFetch({ 'GET /api/about': about, 'GET /api/release-notes': { source: 'none', commits: [] } })
    render(<><input aria-label="field" /><TopNav view="build" monitorTab="runs" automationTab="schedules" onViewChange={vi.fn()} onMonitorTabChange={vi.fn()}
      onAutomationTabChange={vi.fn()} onOpenSettings={vi.fn()} tenantId="t" tenants={[]} projectId="p" user={null}
      projects={[]} onTenantChange={vi.fn()} onProjectChange={vi.fn()} onLogout={vi.fn()} /></>)
    const field = screen.getByLabelText('field')
    field.focus()
    fireEvent.keyDown(field, { key: '?' })
    expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull()
    field.blur()
    fireEvent.keyDown(window, { key: '?' })
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toBeTruthy()
  })
})
