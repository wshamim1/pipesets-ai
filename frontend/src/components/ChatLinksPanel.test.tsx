import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AppRecord } from '../types'
import { stubFetch } from '../test/fetchStub'
import { ChatLinksPanel } from './ChatLinksPanel'

const app = { id: 'app_1', name: 'Weather', status: 'published', version: 3, flow_data: { nodes: [], edges: [] } } as unknown as AppRecord

const link = (id: string, token: string) => ({
  id, app_id: 'app_1', name: `${id} chat`, title: '', greeting: '', access: 'public', token_prefix: token.slice(0, 12), token,
  rate_limit_per_min: 10, max_turns: 50, max_message_chars: 4000, daily_message_cap: 500, show_details: true,
  starter_prompts: [], message_count: 0, last_used_at: null, created_at: '2026-11-01T00:00:00Z', revoked_at: null, active: true,
})

afterEach(() => vi.unstubAllGlobals())

describe('ChatLinksPanel', () => {
  it('creates the first link in one click', async () => {
    let links: unknown[] = []
    const fetchMock = stubFetch({
      'GET /api/chat-links': () => links,
      'POST /api/chat-links': () => { links = [link('chat_a', 'pc_aaaaaaaaaaaaaaaa')]; return links[0] },
    })
    render(<ChatLinksPanel app={app} />)
    fireEvent.click(await screen.findByText('Create chat link'))
    await screen.findByText(/pc_aaaaaaaaaaaaaaaa/)
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true)
  })

  it('shows a single link without a list, and offers another link as a secondary action', async () => {
    stubFetch({ 'GET /api/chat-links': [link('chat_a', 'pc_aaaaaaaaaaaaaaaa')] })
    render(<ChatLinksPanel app={app} />)
    await screen.findByText(/pc_aaaaaaaaaaaaaaaa/)
    expect(screen.queryByText(/chat links$/)).toBeNull()
    expect(screen.getByText(/Add another link/)).toBeTruthy()
  })

  it('gives a link a new URL after confirming', async () => {
    let current = link('chat_a', 'pc_aaaaaaaaaaaaaaaa')
    stubFetch({
      'GET /api/chat-links': () => [current],
      'POST /api/chat-links/chat_a/rotate': () => { current = link('chat_a', 'pc_bbbbbbbbbbbbbbbb'); return current },
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ChatLinksPanel app={app} />)
    await screen.findByText(/pc_aaaaaaaaaaaaaaaa/)
    fireEvent.click(screen.getByText('New URL'))
    await waitFor(() => expect(screen.getByText(/pc_bbbbbbbbbbbbbbbb/)).toBeTruthy())
    expect(screen.queryByText(/pc_aaaaaaaaaaaaaaaa/)).toBeNull()
  })
})
