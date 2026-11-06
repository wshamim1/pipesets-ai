import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../../test/fetchStub'
import { KeyValueStorePanel } from './KeyValueStorePanel'
import type { StoreEntry } from './KeyValueStorePanel'

const entry = (key: string, value: unknown, extra: Partial<StoreEntry> = {}): StoreEntry => ({
  namespace: 'prefs', key, value, expires_at: null,
  created_at: '2026-10-30T10:00:00.000000Z', updated_at: '2026-10-30T10:00:00.000000Z', ...extra,
})

const subjects = {
  subjects: [
    { subject: '', entries: 1, namespaces: ['flags'], last_updated: '2026-10-30T10:00:00.000000Z' },
    { subject: 'alice', entries: 2, namespaces: ['prefs'], last_updated: '2026-10-30T10:00:00.000000Z' },
  ],
}

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('KeyValueStorePanel', () => {
  it('lists shared and per-user entries', async () => {
    const fetch = stubFetch({
      'GET /api/memory/store/subjects': subjects,
      'GET /api/memory/store/entries': (_: unknown, url: string) => ({
        entries: new URL(url).searchParams.get('subject') === 'alice'
          ? [entry('lang', { code: 'fr' }), entry('otp', 1234, { expires_at: '2026-10-31T10:00:00.000000Z' })]
          : [entry('beta', true, { namespace: 'flags' })],
      }),
    })
    render(<KeyValueStorePanel />)
    expect(await screen.findByText('true')).toBeTruthy()      // shared comes first
    fireEvent.click(screen.getByText('alice'))
    expect(await screen.findByText('{"code":"fr"}')).toBeTruthy()
    expect(screen.getByText('expires never')).toBeTruthy()
    expect(fetch.mock.calls.some(([u]) => new URL(String(u)).searchParams.get('subject') === 'alice')).toBe(true)
  })

  it('edits, adds and deletes entries', async () => {
    const fetch = stubFetch({
      'GET /api/memory/store/subjects': { subjects: subjects.subjects.slice(1) },
      'GET /api/memory/store/entries': { entries: [entry('lang', { code: 'fr' })] },
      'PUT /api/memory/store/entries': { stored: true },
      'DELETE /api/memory/store/entries': { deleted: 'lang' },
    })
    render(<KeyValueStorePanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Edit prefs/lang' }))
    fireEvent.change(screen.getByLabelText('Value of prefs/lang'), { target: { value: '{"code": "de"}' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sentBody(fetch, 'PUT /api/memory/store/entries'))
      .toEqual({ subject: 'alice', namespace: 'prefs', key: 'lang', value: { code: 'de' } }))

    fireEvent.change(screen.getByLabelText('New entry key'), { target: { value: 'nickname' } })
    fireEvent.change(screen.getByLabelText('New entry value'), { target: { value: 'Ali' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(sentBody(fetch, 'PUT /api/memory/store/entries', 1))
      .toEqual({ subject: 'alice', namespace: 'default', key: 'nickname', value: 'Ali' }))   // plain text → string

    fireEvent.click(screen.getByRole('button', { name: 'Delete prefs/lang' }))
    await waitFor(() => expect(fetch.mock.calls.some(([u, i]) => i?.method === 'DELETE'
      && new URL(String(u)).searchParams.get('key') === 'lang')).toBe(true))
  })
})
