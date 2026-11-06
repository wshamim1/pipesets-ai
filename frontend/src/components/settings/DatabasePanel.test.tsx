import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { json, stubFetch } from '../../test/fetchStub'
import { DatabasePanel, formatBytes } from './DatabasePanel'
import type { DatabaseInfo } from './DatabasePanel'

const info = (extra: Partial<DatabaseInfo> = {}): DatabaseInfo => ({
  backend: 'postgresql', driver: 'psycopg2', host: 'db.internal', port: 5432, database: 'pipesets',
  server_version: '16.4', size_bytes: 12 * 1024 * 1024,
  schema: { current: '0012_audit_log_time_index', head: '0012_audit_log_time_index', pending: [] },
  ...extra,
})

describe('DatabasePanel', () => {
  it('shows the connection, size and an up-to-date schema', async () => {
    stubFetch({ 'GET /api/system/database': () => info() })
    render(<DatabasePanel />)
    expect(await screen.findByText('PostgreSQL 16.4')).toBeTruthy()
    expect(screen.getByText('db.internal:5432 / pipesets')).toBeTruthy()
    expect(screen.getByText('12 MB')).toBeTruthy()
    expect(screen.getByText(/Up to date/)).toBeTruthy()
    expect(screen.queryByText(/one file on this server/)).toBeNull()
  })

  it('on SQLite, shows the file and says when to use PostgreSQL', async () => {
    stubFetch({ 'GET /api/system/database': () => info({ backend: 'sqlite', host: '', port: null, database: '/data/pipesets.db', server_version: '3.45.3' }) })
    render(<DatabasePanel />)
    expect(await screen.findByText('/data/pipesets.db')).toBeTruthy()
    expect(screen.getByText(/one file on this server/)).toBeTruthy()
  })

  it('lists pending migrations and how to apply them', async () => {
    stubFetch({ 'GET /api/system/database': () => info({ schema: { current: '0010_audit_log', head: '0012_audit_log_time_index',
      pending: [{ revision: '0011_custom_tool_requirements', description: 'Per-tool requirements' },
                { revision: '0012_audit_log_time_index', description: 'Index audit_log' }] } }) })
    render(<DatabasePanel />)
    expect(await screen.findByText(/2 migrations pending/)).toBeTruthy()
    expect(screen.getByText('0011_custom_tool_requirements')).toBeTruthy()
    expect(screen.getByText('python manage.py db setup')).toBeTruthy()
  })

  it('copies the move command', async () => {
    stubFetch({ 'GET /api/system/database': () => info() })
    const writeText = vi.fn(() => Promise.resolve())
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    render(<DatabasePanel />)
    const cmd = await screen.findByText(/manage\.py db copy --to/)
    fireEvent.click(cmd.parentElement!.querySelector('button')!)
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(cmd.textContent))
    expect(await screen.findByText('✓ Copied')).toBeTruthy()
  })

  it('explains a missing permission', async () => {
    stubFetch({ 'GET /api/system/database': () => json({ detail: 'no' }, 403) })
    render(<DatabasePanel />)
    expect((await screen.findByRole('alert')).textContent).toContain('server admin')
  })
})

describe('formatBytes', () => {
  it('picks a readable unit', () => {
    expect([formatBytes(null), formatBytes(512), formatBytes(1536), formatBytes(10 * 1024 ** 3)]).toEqual(['—', '512 B', '1.5 KB', '10 GB'])
  })
})

describe('DatabasePanel — Use PostgreSQL', () => {
  const sqlite = () => info({ backend: 'sqlite', host: '', port: null, database: '/data/pipesets.db', server_version: '3.45.3' })
  const fresh = { can_configure: true, reasons: [], source: 'default', env_file: '/data/.env', pending_restart: null }

  const fill = () => {
    for (const [label, value] of [['Host', 'db.example.com'], ['User', 'app'], ['Password', 'pw']] as const) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
  }

  it('needs a passing test of the same settings before it can switch', async () => {
    const fetch = stubFetch({
      'GET /api/system/database': () => sqlite(),
      'GET /api/system/database/setup': () => fresh,
      'POST /api/system/database/test': () => ({ ok: true, message: 'Connected to PostgreSQL 16.4', empty: true }),
    })
    render(<DatabasePanel />)
    await screen.findByText('Use PostgreSQL')
    const switchBtn = () => screen.getByRole('button', { name: 'Switch to this database' }) as HTMLButtonElement
    expect((screen.getByRole('button', { name: 'Test connection' }) as HTMLButtonElement).disabled).toBe(true)
    fill()
    expect(switchBtn().disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect((await screen.findByRole('status')).textContent).toContain('Connected to PostgreSQL 16.4')
    expect(switchBtn().disabled).toBe(false)

    const sent = JSON.parse(String(fetch.mock.calls.find(([u]) => String(u).endsWith('/test'))![1]!.body))
    expect(sent).toMatchObject({ host: 'db.example.com', port: 5432, database: 'pipesets', user: 'app', sslmode: 'prefer' })

    fireEvent.change(screen.getByLabelText('Host'), { target: { value: 'other.example.com' } })
    expect(switchBtn().disabled).toBe(true)
  })

  it('switches after confirming and asks for a restart', async () => {
    let saved = false
    stubFetch({
      'GET /api/system/database': () => sqlite(),
      'GET /api/system/database/setup': () => (saved
        ? { ...fresh, source: 'env_file', pending_restart: 'postgresql+psycopg2://app:***@db.example.com:5432/pipesets' }
        : fresh),
      'POST /api/system/database/test': () => ({ ok: true, message: 'Connected', empty: true }),
      'POST /api/system/database/setup': () => { saved = true; return { ok: true, restart_required: true } },
    })
    vi.stubGlobal('confirm', vi.fn(() => true))
    render(<DatabasePanel />)
    await screen.findByText('Use PostgreSQL')
    fill()
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    await screen.findByRole('status')
    fireEvent.click(screen.getByRole('button', { name: 'Switch to this database' }))
    expect(await screen.findByText('Restart to finish')).toBeTruthy()
    expect(screen.getByText(/app:\*\*\*@db\.example\.com/)).toBeTruthy()
    expect(screen.queryByText('Use PostgreSQL')).toBeNull()
  })

  it("explains why it can't be set here", async () => {
    stubFetch({
      'GET /api/system/database': () => sqlite(),
      'GET /api/system/database/setup': () => ({ ...fresh, can_configure: false, source: 'environment',
        reasons: ['DATABASE_URL is set by the server\'s environment (e.g. Docker Compose or Kubernetes), so it has to be changed there.'] }),
    })
    render(<DatabasePanel />)
    expect(await screen.findByText(/set by the server's environment/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Test connection' })).toBeNull()
  })
})
