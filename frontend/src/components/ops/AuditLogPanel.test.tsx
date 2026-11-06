import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { json, stubFetch } from '../../test/fetchStub'
import { AuditLogPanel, auditQuery } from './AuditLogPanel'
import type { AuditEntry } from './AuditLogPanel'

const entry = (id: string, extra: Partial<AuditEntry> = {}): AuditEntry => ({
  id, tenant_id: 't', project_id: 'proj_research', actor: 'user_admin', action: 'secret.create', target_id: `sec_${id}`,
  outcome: 'success', status: 201, method: 'POST', path: '/api/secrets', ip: '127.0.0.1',
  created_at: '2026-10-29T10:00:00', ...extra,
})

const POLICY = { retention_days: 90, actions: ['api_key.create', 'audit.export', 'secret.create', 'secret.delete'] }

const queryOf = (fetch: ReturnType<typeof stubFetch>, path: string) =>
  fetch.mock.calls.map(([u]) => new URL(String(u))).filter((u) => u.pathname === path).map((u) => u.searchParams)

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('AuditLogPanel', () => {
  it('lists entries, shows the retention policy and marks denied ones', async () => {
    stubFetch({
      'GET /api/audit-log/policy': () => POLICY,
      'GET /api/audit-log': () => ({ entries: [entry('1'), entry('2', { outcome: 'denied', actor: 'user_analyst', status: 403 })], next_before: null }),
    })
    render(<AuditLogPanel />)
    expect(await screen.findByText('sec_1')).toBeTruthy()
    expect(screen.getByText('90 days')).toBeTruthy()
    expect(screen.getByText('denied').closest('.ops-pipeline-row')?.className).toContain('auditlog-row--denied')
    expect(screen.getByRole('option', { name: 'All secret actions' })).toBeTruthy()
  })

  it('applies filters to the list and to exports', async () => {
    const fetch = stubFetch({
      'GET /api/audit-log/policy': () => POLICY,
      'GET /api/audit-log': () => ({ entries: [], next_before: null }),
      'GET /api/audit-log/export': () => new Response('created_at\n', { headers: { 'Content-Disposition': 'attachment; filename="a.csv"' } }),
    })
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    render(<AuditLogPanel />)
    await screen.findByText(/No audit entries yet/)

    fireEvent.change(await screen.findByLabelText('Action'), { target: { value: 'secret.' } })
    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'denied' } })
    fireEvent.change(screen.getByLabelText('User'), { target: { value: ' user_analyst ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    await screen.findByText(/match these filters/)

    const list = queryOf(fetch, '/api/audit-log').at(-1)!
    expect([list.get('action'), list.get('outcome'), list.get('actor'), list.get('limit')]).toEqual(['secret.', 'denied', 'user_analyst', '100'])

    fireEvent.click(screen.getByRole('button', { name: /JSON Lines/ }))
    await waitFor(() => expect(queryOf(fetch, '/api/audit-log/export')).toHaveLength(1))
    const exp = queryOf(fetch, '/api/audit-log/export')[0]
    expect([exp.get('format'), exp.get('action'), exp.get('outcome')]).toEqual(['jsonl', 'secret.', 'denied'])
  })

  it('pages back with next_before', async () => {
    const fetch = stubFetch({
      'GET /api/audit-log/policy': () => POLICY,
      'GET /api/audit-log': (_init: RequestInit | undefined, url: string) => new URL(url).searchParams.get('before')
        ? { entries: [entry('old')], next_before: null }
        : { entries: [entry('new')], next_before: '2026-10-29T10:00:00' },
    })
    render(<AuditLogPanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Load older entries' }))
    expect(await screen.findByText('sec_old')).toBeTruthy()
    expect(screen.getByText('sec_new')).toBeTruthy()
    expect(queryOf(fetch, '/api/audit-log').at(-1)!.get('before')).toBe('2026-10-29T10:00:00')
    expect(screen.queryByRole('button', { name: 'Load older entries' })).toBeNull()
  })

  it('explains a missing permission', async () => {
    stubFetch({ 'GET /api/audit-log/policy': () => json({}, 403), 'GET /api/audit-log': () => json({ detail: 'no' }, 403) })
    render(<AuditLogPanel />)
    expect((await screen.findByRole('alert')).textContent).toContain('audit:read')
  })
})

describe('auditQuery', () => {
  it('turns local dates into a whole-day UTC range', () => {
    const q = new URLSearchParams(auditQuery({ action: '', actor: '', outcome: '', since: '2026-10-01', until: '2026-10-01' }))
    const since = new Date(q.get('since')! + 'Z')
    const until = new Date(q.get('until')! + 'Z')
    expect(until.getTime() - since.getTime()).toBe(24 * 3600 * 1000)
    expect(since.getHours()).toBe(0)   // midnight local time
  })
})
