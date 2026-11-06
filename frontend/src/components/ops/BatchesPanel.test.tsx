import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../../test/fetchStub'
import type { AppRecord } from '../../types'
import { BatchesPanel } from './BatchesPanel'
import type { Batch } from './BatchesPanel'

const APPS = [
  { id: 'app_1', name: 'Abstractor', version: 2, status: 'published' },
  { id: 'app_2', name: 'Draft only', version: 0, status: 'draft' },
] as AppRecord[]

const COUNTS = { pending: 0, queued: 0, running: 0, retrying: 0, completed: 2, failed: 1, paused: 0, cancelled: 0 }
const batch = (extra: Partial<Batch> = {}): Batch => ({
  id: 'batch_1', app_id: 'app_1', app_name: 'Abstractor', name: 'Q3 leases', prompt_template: 'Lease for {tenant}',
  columns: ['tenant'], concurrency: 2, status: 'done', total: 3, finished: 3, counts: COUNTS, cost_usd: 0.0123,
  avg_latency_ms: 1500, created_at: '2026-11-03T10:00:00', finished_at: '2026-11-03T10:01:00', ...extra,
})

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('BatchesPanel', () => {
  it('starts a batch from an uploaded file with a prompt template', async () => {
    let list: Batch[] = []
    const fetch = stubFetch({
      'GET /api/batches': () => list,
      'POST /api/batches/parse': { columns: ['tenant', 'unit'], rows: [{ tenant: 'Acme', unit: '101' }, { tenant: 'Beta', unit: '102' }],
        total: 2, prompt_template: '' },
      'POST /api/batches': () => { list = [batch({ status: 'running', total: 2, finished: 0 })]; return list[0] },
      'GET /api/batches/batch_1/items': { total: 0, items: [] },
    })
    render(<BatchesPanel apps={APPS} />)
    await screen.findByText('No batches yet.')
    fireEvent.click(screen.getByRole('button', { name: '+ New batch' }))
    // Only published pipelines can run
    expect(screen.queryByText('Draft only (v0)')).toBeNull()

    const file = new File(['tenant,unit\nAcme,101\nBeta,102\n'], 'leases.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByLabelText('Rows'), { target: { files: [file] } })
    expect(await screen.findByText('2 row(s) · columns: tenant, unit')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Abstract the lease for {tenant}, unit {unit}' } })
    expect(screen.getByText('Abstract the lease for Acme, unit 101')).toBeTruthy()

    // An unknown column blocks the run
    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Lease for {floor}' } })
    expect(screen.getByText('No column named floor')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Run 2 row(s)' }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(screen.getByLabelText('Prompt'), { target: { value: 'Lease for {tenant}' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run 2 row(s)' }))
    expect(await screen.findByText('Running')).toBeTruthy()
    expect(sentBody(fetch, 'POST /api/batches')).toMatchObject({
      app_id: 'app_1', prompt_template: 'Lease for {tenant}', name: 'leases', concurrency: 2, retries: 2,
      rows: [{ tenant: 'Acme', unit: '101' }, { tenant: 'Beta', unit: '102' }],
    })
  })

  it('runs a Structured Extract pipeline over uploaded documents with {path}', async () => {
    const extractApp = {
      id: 'app_x', name: 'Lease abstraction', version: 1, status: 'published',
      flow_data: { nodes: [{ id: 't', type: 'tool', data: { toolId: 'structured_extract' } }], edges: [] },
    } as unknown as AppRecord
    let sent: FormData | null = null
    let list: Batch[] = []
    stubFetch({
      'GET /api/batches': () => list,
      'POST /api/batches/documents': (init: RequestInit | undefined) => {
        sent = init?.body as FormData
        list = [batch({ status: 'running', total: 2, finished: 0, source: { kind: 'documents' } })]
        return list[0]
      },
      'GET /api/batches/batch_1/items': { total: 0, items: [] },
    })
    render(<BatchesPanel apps={[extractApp]} />)
    await screen.findByText('No batches yet.')
    fireEvent.click(screen.getByRole('button', { name: '+ New batch' }))
    fireEvent.click(screen.getByRole('radio', { name: 'Documents' }))

    const files = [new File(['%PDF'], 'maple.pdf'), new File(['%PDF'], 'oak.pdf')]
    fireEvent.change(screen.getByLabelText('Documents'), { target: { files } })
    expect(screen.getByText(/2 file\(s\)/)).toBeTruthy()
    expect((screen.getByLabelText('Prompt') as HTMLTextAreaElement).value).toBe('{path}')   // the tool loads the file
    expect(screen.getByText('…/maple.pdf')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Read with'), { target: { value: 'docling' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run 2 document(s)' }))

    expect(await screen.findByText('Running')).toBeTruthy()
    const form = sent as unknown as FormData
    expect(form.getAll('files').map((f) => (f as File).name)).toEqual(['maple.pdf', 'oak.pdf'])
    expect(form.get('app_id')).toBe('app_x')
    expect(form.get('prompt_template')).toBe('{path}')
    expect(form.get('loader')).toBe('docling')
  })

  it('shows a batch’s rows and retries the failed ones', async () => {
    const fetch = stubFetch({
      'GET /api/batches': [batch()],
      'GET /api/batches/batch_1/items': { total: 3, items: [
        { id: 'i1', idx: 0, prompt: 'Lease for Acme', status: 'completed', attempts: 1, run_id: 'r1', version: 2,
          output: 'Ends 2031-06-30', error: null, latency_ms: 1200, cost_usd: 0.004 },
        { id: 'i3', idx: 2, prompt: 'Lease for Gamma', status: 'failed', attempts: 3, run_id: 'r3', version: 2,
          output: null, error: 'Provider timeout', latency_ms: 0, cost_usd: 0 },
      ] },
      'POST /api/batches/batch_1/retry': batch({ status: 'running' }),
    })
    render(<BatchesPanel apps={APPS} />)
    fireEvent.click(await screen.findByText('Q3 leases'))
    expect(await screen.findByText('Ends 2031-06-30')).toBeTruthy()
    expect(screen.getByText('Provider timeout')).toBeTruthy()
    expect(screen.getByText('3 / 3')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry failed' }))
    await waitFor(() => expect(fetch.mock.calls.some(([u, i]) => String(u).endsWith('/api/batches/batch_1/retry') && i?.method === 'POST')).toBe(true))
  })
})
