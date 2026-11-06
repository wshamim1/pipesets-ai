import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { json, stubFetch } from '../../test/fetchStub'
import { JobsPanel } from './JobsPanel'
import type { Job } from './JobsPanel'

const job = (id: string, extra: Partial<Job> = {}): Job => ({
  id, kind: 'notify.deliver', label: `Notification · ops · run.failed ${id}`, status: 'dead', attempts: 3, max_attempts: 3,
  last_error: 'HTTP 500: down', created_at: '2026-10-29T10:00:00.000000Z', updated_at: '2026-10-29T10:05:00.000000Z',
  finished_at: '2026-10-29T10:05:00.000000Z', source: { type: 'notification_channels', id: 'ch_1' }, ...extra,
})

const COUNTS = { queued: 0, running: 0, done: 4, dead: 1 }

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('JobsPanel', () => {
  it('lists dead jobs and retries one', async () => {
    let dead = [job('1')]
    const fetch = stubFetch({
      'GET /api/jobs': () => ({ jobs: dead, counts: COUNTS }),
      'POST /api/jobs/1/retry': () => { dead = []; return { id: '1', status: 'queued' } },
    })
    render(<JobsPanel />)
    expect(await screen.findByText('Notification · ops · run.failed 1')).toBeTruthy()
    expect(screen.getByText('HTTP 500: down')).toBeTruthy()
    expect(screen.getByText('3 / 3')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('No failed jobs.')
    expect(fetch.mock.calls.some(([u, i]) => String(u).endsWith('/api/jobs/1/retry') && i?.method === 'POST')).toBe(true)
  })

  it('asks before discarding and shows refusals', async () => {
    stubFetch({
      'GET /api/jobs': () => ({ jobs: [job('2')], counts: COUNTS }),
      'DELETE /api/jobs/2': () => json({ detail: 'nope' }, 403),
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    render(<JobsPanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Discard' }))
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('alert')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/write access/))
  })

  it('cancels a running job after asking', async () => {
    const fetch = stubFetch({
      'GET /api/jobs': (_init: unknown, url: string) => new URL(url).searchParams.get('status') === 'running'
        ? { jobs: [job('4', { status: 'running', last_error: null })], counts: COUNTS }
        : { jobs: [], counts: COUNTS },
      'POST /api/jobs/4/cancel': () => ({ id: '4', status: 'cancelling' }),
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<JobsPanel />)
    await screen.findByText('No failed jobs.')
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'running' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(fetch.mock.calls.some(([u, i]) =>
      String(u).endsWith('/api/jobs/4/cancel') && i?.method === 'POST')).toBe(true))
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
  })

  it('switches status; only failed jobs can be retried', async () => {
    const fetch = stubFetch({
      'GET /api/jobs': (_init: unknown, url: string) => new URL(url).searchParams.get('status') === 'done'
        ? { jobs: [job('3', { status: 'done', last_error: null })], counts: COUNTS }
        : { jobs: [], counts: COUNTS },
    })
    render(<JobsPanel />)
    await screen.findByText('No failed jobs.')
    expect(screen.getByRole('option', { name: 'Done (4)' })).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'done' } })
    expect(await screen.findByText('Notification · ops · run.failed 3')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Retry' })).toBeNull()
    expect(screen.getByText('Finished')).toBeTruthy()
    expect(fetch.mock.calls.map(([u]) => new URL(String(u)).searchParams.get('status'))).toEqual(['dead', 'done'])
  })
})
