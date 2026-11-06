import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../test/fetchStub'
import { CustomToolModal } from './CustomToolModal'
import type { CustomToolRecord } from './CustomToolModal'

const TYPED = {
  ok: true, legacy: false, entrypoint: 'weather',
  parameters: { required: ['city'], properties: { city: { type: 'string', description: 'City name' },
                                                  units: { enum: ['metric', 'imperial'], default: 'metric' } } },
}

const deployed: CustomToolRecord = {
  id: 't1', name: 'weather', icon: '☀️', description: 'Weather', code: 'from pipesets import tool\n',
  config_keys: [], requirements: [], created_at: '2026-10-30T10:00:00', updated_at: '2026-10-30T10:00:00',
  version: 3, source: 'sdk', read_only: true,
}

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('CustomToolModal', () => {
  it('shows the parameters the model will call the tool with, and tests with arguments', async () => {
    const fetch = stubFetch({
      'POST /api/custom-tools/signature': () => TYPED,
      'POST /api/custom-tools/execute-code': () => ({ success: true, output: '{"city": "Oslo"}' }),
    })
    render(<CustomToolModal onSaved={vi.fn()} onClose={vi.fn()} />)
    expect(await screen.findByText('city: string (required) — City name')).toBeTruthy()
    expect(screen.getByText('units: metric | imperial = "metric"')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Test' }))
    fireEvent.change(screen.getByPlaceholderText('{"city":"…"}'), { target: { value: '{"city": "Oslo"}' } })
    fireEvent.click(screen.getByRole('button', { name: '▶ Run Test' }))
    expect(await screen.findByText('{"city": "Oslo"}')).toBeTruthy()
    expect(sentBody(fetch, 'POST /api/custom-tools/execute-code').args).toEqual({ city: 'Oslo' })
  })

  it('explains why code can’t be a tool', async () => {
    stubFetch({ 'POST /api/custom-tools/signature': () => ({ ok: false, error: 'Define the tool as a function decorated with @tool' }) })
    render(<CustomToolModal onSaved={vi.fn()} onClose={vi.fn()} />)
    expect(await screen.findByText(/⚠ Define the tool as a function/)).toBeTruthy()
  })

  it('keeps SDK-deployed tools read-only, with fork and rollback', async () => {
    const onSaved = vi.fn()
    const fetch = stubFetch({
      'POST /api/custom-tools/signature': () => TYPED,
      'GET /api/custom-tools/t1/versions': () => ({ current: 3, versions: [
        { version: 3, source: 'sdk', note: 'def456', created_at: '2026-10-30T10:00:00', created_by: 'ci' },
        { version: 2, source: 'sdk', note: 'abc123', created_at: '2026-10-29T10:00:00', created_by: 'ci' }] }),
      'POST /api/custom-tools/t1/rollback': () => ({ ...deployed, version: 4 }),
      'POST /api/custom-tools/t1/fork': () => ({ ...deployed, id: 't2', name: 'weather (fork)', read_only: false }),
    })
    render(<CustomToolModal tool={deployed} onSaved={onSaved} onClose={vi.fn()} />)
    expect(screen.getByText('Deployed from SDK')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Save Changes' })).toBeNull()
    expect((screen.getByDisplayValue('from pipesets import tool') as HTMLTextAreaElement).readOnly).toBe(true)

    fireEvent.click(screen.getByRole('button', { name: 'Versions' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Roll back to this' }))
    await waitFor(() => expect(sentBody(fetch, 'POST /api/custom-tools/t1/rollback')).toEqual({ version: 2 }))
    expect(onSaved).toHaveBeenLastCalledWith(expect.objectContaining({ version: 4 }))

    fireEvent.click(screen.getByRole('button', { name: 'Fork to edit' }))
    await waitFor(() => expect(onSaved).toHaveBeenLastCalledWith(expect.objectContaining({ id: 't2' })))
  })
})
