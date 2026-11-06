import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '../test/fetchStub'
import { TopNav } from './TopNav'
import { WhatsNewPanel } from './WhatsNewPanel'

const commit = {
  hash: 'a'.repeat(40), short: 'aaaaaaa', date: '2026-11-04T10:00:00+00:00', author: 'Ana Dev',
  subject: 'Add observability tools', body: 'Grafana, Loki and Tempo.',
  files: [{ path: 'backend/tools/grafana.py', added: 120, removed: 0 }, { path: 'frontend/src/App.tsx', added: 3, removed: 1 },
    { path: 'backend/tests/test_x.py', added: 40, removed: 0 }],
  areas: [{ area: 'Backend', files: 1, added: 120, removed: 0 }, { area: 'Tests', files: 1, added: 40, removed: 0 },
    { area: 'Frontend', files: 1, added: 3, removed: 1 }],
}

function renderNav() {
  render(<TopNav view="build" monitorTab="runs" automationTab="schedules" onViewChange={vi.fn()} onMonitorTabChange={vi.fn()}
    onAutomationTabChange={vi.fn()} onOpenSettings={vi.fn()} tenantId="t" tenants={[]} projectId="p" user={null}
    projects={[]} onTenantChange={vi.fn()} onProjectChange={vi.fn()} onLogout={vi.fn()} />)
}

describe("What's new", () => {
  beforeEach(() => { localStorage.clear() })

  it('shows the latest commit and what it changed, by area', async () => {
    stubFetch({ 'GET /api/release-notes': { source: 'git', commits: [commit] } })
    render(<WhatsNewPanel onClose={vi.fn()} />)
    expect(await screen.findByText('Add observability tools')).toBeTruthy()
    expect(screen.getByText('Grafana, Loki and Tempo.')).toBeTruthy()
    expect(screen.getByText(/Ana Dev/).textContent).toContain('aaaaaaa')
    expect(screen.queryByText('backend/tools/grafana.py')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Backend/ }))
    expect(screen.getByText('backend/tools/grafana.py')).toBeTruthy()
    expect(screen.queryByText('backend/tests/test_x.py')).toBeNull()   // tests are their own area
  })

  it('says so when the build has no release notes', async () => {
    stubFetch({ 'GET /api/release-notes': { source: 'none', commits: [] } })
    render(<WhatsNewPanel onClose={vi.fn()} />)
    expect(await screen.findByText(/aren't available in this build/)).toBeTruthy()
  })

  it('marks a new release with a dot on the top-nav button until it is opened', async () => {
    stubFetch({ 'GET /api/release-notes': { source: 'git', commits: [commit] } })
    renderNav()
    const button = await screen.findByRole('button', { name: "What's new (new release)" })
    fireEvent.click(button)
    expect(await screen.findByRole('dialog')).toBeTruthy()
    await waitFor(() => expect(screen.getByRole('button', { name: "What's new" })).toBeTruthy())
    expect(localStorage.getItem('pipesets:release-notes-seen')).toBe(commit.hash)

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('shows no dot for a release already seen', async () => {
    localStorage.setItem('pipesets:release-notes-seen', commit.hash)
    const fetchMock = stubFetch({ 'GET /api/release-notes': { source: 'git', commits: [commit] } })
    renderNav()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: "What's new" })).toBeTruthy()
  })
})
