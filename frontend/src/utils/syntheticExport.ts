import type { SyntheticDataNodeData } from '../types'

type Row = Record<string, unknown>

const MIME = { json: 'application/json', jsonl: 'application/x-ndjson', csv: 'text/csv;charset=utf-8' } as const

/** Every key that appears in any row, in first-seen order. */
export function rowHeaders(rows: Row[]): string[] {
  const out: string[] = []
  for (const row of rows) for (const k of Object.keys(row)) if (!out.includes(k)) out.push(k)
  return out
}

function csvCell(v: unknown): string {
  const s = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v)
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** Generated rows in the node's output format, ready to save. */
export function rowsToFile(rows: Row[], format: SyntheticDataNodeData['output_format'], datasetName: string) {
  const base = (datasetName || 'synthetic_dataset').replace(/[^\w.-]+/g, '_')
  let content: string
  if (format === 'csv') {
    const headers = rowHeaders(rows)
    content = [headers.map(csvCell).join(','), ...rows.map((r) => headers.map((h) => csvCell(r[h])).join(','))].join('\r\n') + '\r\n'
  } else if (format === 'jsonl') {
    content = rows.map((r) => JSON.stringify(r)).join('\n') + '\n'
  } else {
    content = JSON.stringify(rows, null, 2)
  }
  return { content, mime: MIME[format] ?? MIME.json, filename: `${base}.${format}` }
}

const PROMPT_NAMES = ['prompt', 'question', 'input', 'query', 'user_input', 'instruction', 'text']
const EXPECTED_NAMES = ['expected_output', 'expected', 'answer', 'output', 'response', 'label', 'target']

/** Best guess at which columns hold the eval prompt and the expected answer ("" = none). */
export function guessCaseColumns(headers: string[]): { prompt: string; expected: string } {
  const find = (names: string[]) => names.map((n) => headers.find((h) => h.toLowerCase() === n)).find(Boolean) ?? ''
  return { prompt: find(PROMPT_NAMES), expected: find(EXPECTED_NAMES) }
}
