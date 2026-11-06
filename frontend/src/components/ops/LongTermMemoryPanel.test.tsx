import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '../../test/fetchStub'
import { LongTermMemoryPanel } from './LongTermMemoryPanel'
import type { Fact } from './LongTermMemoryPanel'

const fact = (id: string, content: string, extra: Partial<Fact> = {}): Fact => ({
  id, subject: 'alice', content, source: 'extracted', app_id: 'app-1',
  created_at: '2026-10-29T10:00:00', updated_at: '2026-10-29T10:00:00', last_used_at: null, ...extra,
})

const called = (fetch: ReturnType<typeof stubFetch>, method: string, path: string) =>
  fetch.mock.calls.some(([u, i]) => new URL(String(u)).pathname === path && (i?.method ?? 'GET') === method)

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('LongTermMemoryPanel', () => {
  it('shows each user’s facts and the workspace switch', async () => {
    let enabled = false
    const fetch = stubFetch({
      'GET /api/memory/long-term/settings': () => ({ enabled, can_change: true }),
      'PUT /api/memory/long-term/settings': () => { enabled = true; return { enabled, can_change: true } },
      'GET /api/memory/long-term/users': () => ({ users: [{ subject: 'alice', facts: 2, last_updated: '2026-10-29T10:00:00' }] }),
      'GET /api/memory/long-term/facts': () => ({ facts: [fact('1', 'Is vegetarian'), fact('2', 'Likes metric units', { source: 'manual' })] }),
    })
    render(<LongTermMemoryPanel />)
    expect(await screen.findByText('Is vegetarian')).toBeTruthy()
    expect(screen.getByText('added by hand')).toBeTruthy()
    expect(screen.getByText('Off for this workspace')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Turn on' }))
    expect(await screen.findByText('On for this workspace')).toBeTruthy()
    expect(called(fetch, 'PUT', '/api/memory/long-term/settings')).toBe(true)
  })

  it('deletes a fact, adds one and forgets a user', async () => {
    const fetch = stubFetch({
      'GET /api/memory/long-term/settings': () => ({ enabled: true, can_change: false }),
      'GET /api/memory/long-term/users': () => ({ users: [{ subject: 'alice', facts: 1, last_updated: '2026-10-29T10:00:00' }] }),
      'GET /api/memory/long-term/facts': () => ({ facts: [fact('1', 'Is vegetarian')] }),
      'DELETE /api/memory/long-term/facts/1': () => ({ deleted: '1' }),
      'POST /api/memory/long-term/facts': () => ({ stored: ['Is left-handed'] }),
      'DELETE /api/memory/long-term/users/alice': () => ({ user: 'alice', deleted: 1 }),
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<LongTermMemoryPanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Delete “Is vegetarian”' }))
    await waitFor(() => expect(called(fetch, 'DELETE', '/api/memory/long-term/facts/1')).toBe(true))

    fireEvent.change(screen.getByLabelText('New fact'), { target: { value: 'Is left-handed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(called(fetch, 'POST', '/api/memory/long-term/facts')).toBe(true))

    fireEvent.click(screen.getByRole('button', { name: 'Forget this user' }))
    await waitFor(() => expect(called(fetch, 'DELETE', '/api/memory/long-term/users/alice')).toBe(true))
    expect(screen.queryByRole('button', { name: 'Turn on' })).toBeNull()   // only owners see the switch
  })
})
