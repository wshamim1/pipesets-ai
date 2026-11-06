import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../../test/fetchStub'
import { FeedbackPanel } from './FeedbackPanel'
import type { FeedbackItem } from './FeedbackPanel'

const item = (id: string, extra: Partial<FeedbackItem> = {}): FeedbackItem => ({
  id, app_id: 'app_1', app_name: 'Lease bot', app_version: 2, run_id: `run_${id}`, source: 'chat_link',
  rater: 'chat visitor', rating: -1, comment: 'wrong date', correction: '', prompt: `When does lease ${id} end?`,
  output: 'In 2030.', dataset_id: null, updated_at: '2026-11-03T10:00:00', ...extra,
})

const SUMMARY = [{ app_id: 'app_1', app_name: 'Lease bot', version: 2, up: 1, down: 3, total: 4, comments: 2,
  satisfaction: 0.25, last_at: '2026-11-03T10:00:00' }]

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('FeedbackPanel', () => {
  it('shows satisfaction per version and the 👎 ratings with their notes', async () => {
    const fetch = stubFetch({
      'GET /api/feedback/summary': SUMMARY,
      'GET /api/feedback': { total: 1, items: [item('a')] },
    })
    render(<FeedbackPanel datasets={[]} />)
    expect(await screen.findByText('When does lease a end?')).toBeTruthy()
    expect(screen.getByText('25%')).toBeTruthy()
    expect(screen.getByText('“wrong date”')).toBeTruthy()
    expect(fetch.mock.calls.some(([u]) => String(u).includes('/api/feedback?') && String(u).includes('rating=-1'))).toBe(true)
    fireEvent.click(screen.getByText('When does lease a end?'))
    expect(screen.getByText('In 2030.')).toBeTruthy()
  })

  it('exports selected ratings to a new dataset', async () => {
    const onExported = vi.fn()
    const fetch = stubFetch({
      'GET /api/feedback/summary': SUMMARY,
      'GET /api/feedback': { total: 2, items: [item('a'), item('b')] },
      'POST /api/feedback/export': { dataset_id: 'ds_1', cases_created: 1, skipped_duplicates: 0, exported: 1 },
    })
    render(<FeedbackPanel datasets={[]} onExported={onExported} />)
    await screen.findByText('When does lease a end?')
    const exportBtn = screen.getByRole('button', { name: 'Export' }) as HTMLButtonElement
    expect(exportBtn.disabled).toBe(true)
    fireEvent.click(screen.getAllByLabelText('Select')[1])
    fireEvent.change(screen.getByPlaceholderText('New dataset name'), { target: { value: 'From users' } })
    fireEvent.click(exportBtn)
    expect(await screen.findByText('Added 1 case(s).')).toBeTruthy()
    expect(sentBody(fetch, 'POST /api/feedback/export')).toEqual({ feedback_ids: ['b'], dataset_id: '', dataset_name: 'From users' })
    expect(onExported).toHaveBeenCalled()
  })
})
