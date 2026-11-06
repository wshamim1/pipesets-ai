import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../../test/fetchStub'
import { findQuote, ReviewQueue, typedValue } from './ReviewQueue'
import type { ReviewItem } from './ReviewQueue'

const item = (extra: Partial<ReviewItem>): ReviewItem => ({
  id: 'rv_1', batch: 'maple', source: '/data/leases/lease.pdf', field: 'lease_end', description: 'Lease expiration date',
  field_type: 'date', value: '2034-12-31', page: 2, page_label: null, quote: 'expires on December 31, 2034',
  confidence: 0.95, verified: true, status: 'pending', final_value: null, note: '', model: 'openai/gpt-4o-mini',
  reviewed_by: null, reviewed_at: null, created_at: '2026-11-02T10:00:00', prompt_version: 'pv_0123456789',
  alternatives: [], conflict: false, bulk: false, ...extra,
})
const RENT = item({ id: 'rv_2', field: 'monthly_base_rent', field_type: 'money', value: 18500, verified: false,
  confidence: 0.3, quote: 'monthly base rent of $185,000.00' })
const GUARANTOR = item({ id: 'rv_3', field: 'guarantor', value: null, quote: null, page: null, confidence: 0 })
const COUNTS = { pending: 3, approved: 0, corrected: 0, rejected: 0 }

describe('ReviewQueue', () => {
  beforeEach(() => { vi.unstubAllGlobals() })

  it('shows each field with its citation and whether the quote was found', async () => {
    stubFetch({ 'GET /api/reviews': { items: [item({}), RENT, GUARANTOR], counts: COUNTS } })
    render(<ReviewQueue />)
    expect(await screen.findByText('📄 lease.pdf')).toBeTruthy()
    expect(screen.getByText('To review (3)')).toBeTruthy()
    const lease = screen.getByTestId('review-lease_end')
    expect(lease.textContent).toContain('✓ quote found')
    expect(lease.textContent).toContain('“expires on December 31, 2034” — page 2')
    expect(screen.getByTestId('review-monthly_base_rent').textContent).toContain('quote not found')
    const guarantor = screen.getByTestId('review-guarantor')
    expect(guarantor.textContent).toContain('not found')
    expect(guarantor.textContent).not.toContain('Approve')
  })

  it('approves, and corrects with a typed value', async () => {
    const fetchMock = stubFetch({
      'GET /api/reviews': { items: [item({}), RENT], counts: COUNTS },
      'POST /api/reviews/rv_1/decision': item({ status: 'approved' }),
      'POST /api/reviews/rv_2/decision': { ...RENT, status: 'corrected' },
    })
    render(<ReviewQueue />)
    const lease = await screen.findByTestId('review-lease_end')
    fireEvent.click(lease.querySelector('button')!)
    await waitFor(() => expect(sentBody(fetchMock, 'POST /api/reviews/rv_1/decision')).toEqual({ decision: 'approve' }))

    fireEvent.click(screen.getAllByText('Correct')[1])
    fireEvent.change(screen.getByLabelText('Correct monthly_base_rent'), { target: { value: '$185,000.00' } })
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(sentBody(fetchMock, 'POST /api/reviews/rv_2/decision'))
      .toEqual({ decision: 'correct', value: 185000 }))
  })

  it('exports reviewed documents and shows backend errors', async () => {
    const onExported = vi.fn()
    let calls = 0
    const fetchMock = stubFetch({
      'GET /api/reviews': { items: [], counts: COUNTS },
      'POST /api/reviews/export': () => (++calls === 1
        ? new Response(JSON.stringify({ detail: 'No reviewed documents to export yet' }), { status: 409 })
        : { dataset_id: 'ds1', cases_created: 2, skipped_duplicates: 0, replaced: 0, documents: 2 }),
    })
    render(<ReviewQueue onExported={onExported} />)
    expect(await screen.findByText(/Nothing to review/)).toBeTruthy()
    fireEvent.click(screen.getByText('Export'))
    expect(await screen.findByText('No reviewed documents to export yet')).toBeTruthy()
    fireEvent.click(screen.getByText('Export'))
    expect(await screen.findByText('2 new cases added (0 already there).')).toBeTruthy()
    expect(sentBody(fetchMock, 'POST /api/reviews/export', 1)).toEqual({ dataset_name: 'Reviewed extractions', batch: '' })
    expect(onExported).toHaveBeenCalledOnce()
  })

  it('opens the cited page with the quote marked, and an alternative from another part', async () => {
    const rent = item({
      id: 'rv_4', field: 'monthly_base_rent', field_type: 'money', value: 185000, quote: 'monthly base rent of $185,000.00',
      conflict: true, confidence: 0.5,
      alternatives: [{ value: 190000, page: 7, page_label: null, quote: 'base rent of $190,000.00', verified: true, confidence: 0.8 }],
    })
    const fetchMock = stubFetch({
      'GET /api/reviews': { items: [rent], counts: COUNTS },
      'GET /api/reviews/rv_4/page': (_: unknown, url: string) => (url.includes('page=7')
        ? { page: 7, page_label: null, text: 'First Amendment: base rent of $190,000.00 from 2027.' }
        : { page: 2, page_label: null, text: '4.2 Base Rent. Tenant shall pay monthly\nbase rent of $185,000.00 each month.' }),
      'POST /api/reviews/rv_4/decision': { ...rent, status: 'corrected' },
      '*': { matching: 0, approved: 0, ids: [] },
    })
    render(<ReviewQueue />)
    const row = await screen.findByTestId('review-monthly_base_rent')
    expect(row.textContent).toContain('parts disagree')
    expect(screen.getByTestId('review-alt-monthly_base_rent-0').textContent).toContain('190000')

    fireEvent.click(screen.getByText('📄 Page'))
    const page = await screen.findByTestId('review-page-monthly_base_rent')
    await waitFor(() => expect(page.querySelector('mark')?.textContent).toBe('monthly\nbase rent of $185,000.00'))
    expect(page.textContent).toContain('each month.')

    fireEvent.click(screen.getByText('📄 Page 7'))
    await waitFor(() => expect(screen.getByTestId('review-page-monthly_base_rent').querySelector('mark')?.textContent)
      .toBe('base rent of $190,000.00'))

    fireEvent.click(screen.getByText('Use this value'))
    await waitFor(() => expect(sentBody(fetchMock, 'POST /api/reviews/rv_4/decision')).toEqual({ decision: 'correct', value: 190000 }))
  })

  it('bulk-approves verified fields above the threshold', async () => {
    const fetchMock = stubFetch({
      'GET /api/reviews': { items: [item({})], counts: COUNTS },
      'GET /api/reviews/bulk-approve': (_: unknown, url: string) =>
        ({ matching: url.includes('min_confidence=0.9') ? 2 : 5, approved: 0, ids: [] }),
      'POST /api/reviews/bulk-approve': { matching: 2, approved: 2, ids: ['rv_1', 'rv_9'] },
    })
    render(<ReviewQueue />)
    expect(await screen.findByText('Approve 2 fields')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Bulk approve fields with a found quote at'), { target: { value: '70' } })
    expect(await screen.findByText('Approve 5 fields')).toBeTruthy()
    fireEvent.click(screen.getByText('Approve 5 fields'))
    await waitFor(() => expect(sentBody(fetchMock, 'POST /api/reviews/bulk-approve')).toEqual({ min_confidence: 0.7, batch: '' }))
  })

  it('shows per-field accuracy by model and prompt version', async () => {
    const counts = { right: 3, wrong: 1, bulk: 2, pending: 0, checked: 4, accuracy: 0.75, approved: 4, corrected: 1, rejected: 1 }
    stubFetch({
      'GET /api/reviews': { items: [], counts: COUNTS },
      'GET /api/reviews/report': { groups: [{ model: 'openai/gpt-4o-mini', prompt_version: 'pv_abc', ...counts,
        fields: [{ field: 'monthly_base_rent', ...counts, accuracy: 0.5 }] }] },
      '*': { matching: 0, approved: 0, ids: [] },
    })
    render(<ReviewQueue />)
    fireEvent.click(screen.getByText('Accuracy'))
    const group = await screen.findByTestId('report-pv_abc')
    expect(group.textContent).toContain('openai/gpt-4o-mini · pv_abc — 75% of 4 checked')
    expect(group.querySelector('tbody tr')?.textContent).toBe('monthly base rent50%3120')
  })

  it('finds a quote across line breaks and punctuation', () => {
    expect(findQuote('Rent: $1,000\nper month.', 'rent $1,000 per month')).toEqual(['', 'Rent: $1,000\nper month', '.'])
    expect(findQuote('nothing here', 'rent')).toBeNull()
    expect(findQuote('text', null)).toBeNull()
  })

  it('types corrected values by field type', () => {
    expect(typedValue('$1,250.50', 'money')).toBe(1250.5)
    expect(typedValue('n/a', 'money')).toBe('n/a')
    expect(typedValue('TRUE', 'boolean')).toBe(true)
    expect(typedValue(' 2034-12-31 ', 'date')).toBe('2034-12-31')
  })
})
