import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FlowNode } from '../../types'
import { sentBody, stubFetch } from '../../test/fetchStub'
import { SyntheticDataConfigPanel } from './SyntheticDataConfigPanel'

const data = {
  label: 'FAQ data', dataset_name: 'faq', row_count: 3, output_format: 'csv', schema_mode: 'manual', schema_json: '',
  columns: [{ id: 'c1', name: 'question', type: 'string', nullable: false, unique: true }],
  locale: 'en_US', seed: 42, strict_schema: true, include_edge_cases: false, prompt_instructions: '',
}
const rows = [{ id: 1, question: 'Q1', answer: 'A1' }, { id: 2, question: 'Q2', answer: 'A2' }, { id: 3, question: 'Q3', answer: 'A3' }]
const ndjson = (...lines: unknown[]) =>
  new Response(lines.map((l) => JSON.stringify(l)).join('\n') + '\n', { headers: { 'Content-Type': 'application/x-ndjson' } })

function renderPanel(extra: Record<string, unknown> = {}) {
  const activeNode = { id: 'n1', type: 'synthetic_data', position: { x: 0, y: 0 }, data: { ...data, ...extra } } as unknown as FlowNode
  return render(<SyntheticDataConfigPanel activeNode={activeNode} onUpdate={vi.fn()} onDelete={vi.fn()} onSave={vi.fn()} />)
}

afterEach(() => vi.unstubAllGlobals())

describe('SyntheticDataConfigPanel — full dataset', () => {
  it('generates every row, then saves them as eval cases with the guessed columns', async () => {
    const fetchMock = stubFetch({
      'GET /api/eval/datasets': [{ id: 'd1', name: 'Existing', case_count: 4 }],
      'POST /api/eval/synthetic-generate': () => ndjson(
        { type: 'progress', rows: 2, total: 3 },
        { type: 'done', rows, model_used: 'openai/gpt-4o', requested: 3, generated: 3, failed_batches: 0, dropped_rows: 1 },
      ),
      'POST /api/eval/synthetic-save': { dataset_id: 'd2', cases_created: 3, skipped_duplicates: 0, replaced: 0, rows: 3 },
    })
    renderPanel()
    fireEvent.click(screen.getByText('Generate All 3 Rows'))
    await screen.findByText(/Generated 3 of 3 rows\. 1 invalid or duplicate row\(s\) replaced\./)
    expect(screen.getByText('3 generated rows ready.')).toBeTruthy()
    expect(sentBody(fetchMock, 'POST /api/eval/synthetic-generate')).toMatchObject({ row_count: 3, dataset_name: 'faq' })

    expect((screen.getByLabelText('Prompt column') as HTMLSelectElement).value).toBe('question')
    expect((screen.getByLabelText('Expected output column') as HTMLSelectElement).value).toBe('answer')
    await screen.findByText('Existing (4 cases)')

    fireEvent.click(screen.getByText('Save 3 Rows as Eval Cases'))
    await screen.findByText(/Saved 3 case\(s\) to "faq"/)
    expect(sentBody(fetchMock, 'POST /api/eval/synthetic-save')).toEqual({
      rows, dataset_id: null, dataset_name: 'faq', prompt_column: 'question', expected_column: 'answer',
    })
  })

  it('shows the server error and caps the row count', async () => {
    stubFetch({
      'GET /api/eval/datasets': [],
      'POST /api/eval/synthetic-generate': () => new Response(JSON.stringify({ detail: 'No API key for openai.' }), { status: 400 }),
    })
    renderPanel()
    fireEvent.click(screen.getByText('Generate All 3 Rows'))
    await screen.findByText('No API key for openai.')

    renderPanel({ row_count: 5000 })
    expect((screen.getByText('Generate All 5000 Rows') as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText(/limited to 1000 rows/)).toBeTruthy()
  })

  it('saves preview rows when there is no full run yet', () => {
    stubFetch({ 'GET /api/eval/datasets': [] })
    renderPanel({ generated_preview_rows: rows.slice(0, 2) })
    expect(screen.getByText(/download and save use the 2 preview rows/)).toBeTruthy()
    expect(screen.getByText('Save 2 Rows as Eval Cases')).toBeTruthy()
  })
})
