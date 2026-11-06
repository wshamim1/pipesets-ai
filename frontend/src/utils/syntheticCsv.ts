import type { SyntheticDataColumn, SyntheticDataColumnType } from '../types'

function splitCsvRows(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let inQuotes = false

  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"'
          i += 1
        } else {
          inQuotes = false
        }
      } else {
        field += ch
      }
      continue
    }
    if (ch === '"') {
      inQuotes = true
      continue
    }
    if (ch === ',') {
      row.push(field)
      field = ''
      continue
    }
    if (ch === '\n') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''
      continue
    }
    if (ch !== '\r') field += ch
  }
  row.push(field)
  rows.push(row)
  return rows.filter((r) => r.some((c) => String(c).trim() !== ''))
}

export function parseCsvRecords(text: string): Array<Record<string, string>> {
  const rows = splitCsvRows(text)
  if (rows.length < 2) return []
  const headers = rows[0].map((h, idx) => {
    const clean = String(h || '').trim()
    return clean || `column_${idx + 1}`
  })
  return rows.slice(1).map((values) => {
    const record: Record<string, string> = {}
    headers.forEach((h, i) => { record[h] = String(values[i] ?? '').trim() })
    return record
  })
}

function inferType(values: string[]): SyntheticDataColumnType {
  const nonEmpty = values.filter((v) => v !== '')
  if (nonEmpty.length === 0) return 'string'
  if (nonEmpty.every((v) => /^(true|false)$/i.test(v))) return 'boolean'
  if (nonEmpty.every((v) => /^-?\d+$/.test(v))) return 'integer'
  if (nonEmpty.every((v) => /^-?\d+(\.\d+)?$/.test(v))) return 'number'
  if (nonEmpty.every((v) => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(v))) return 'uuid'
  if (nonEmpty.every((v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v))) return 'email'
  if (nonEmpty.every((v) => /^\d{4}-\d{2}-\d{2}$/.test(v))) return 'date'
  if (nonEmpty.every((v) => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v))) return 'datetime'
  const uniq = Array.from(new Set(nonEmpty))
  if (uniq.length >= 2 && uniq.length <= 8) return 'category'
  return 'string'
}

export function inferColumnsFromCsv(records: Array<Record<string, string>>): SyntheticDataColumn[] {
  if (!records.length) return []
  const headers = Object.keys(records[0])
  return headers.map((name, idx) => {
    const values = records.map((r) => String(r[name] ?? '').trim())
    const nonEmpty = values.filter((v) => v !== '')
    const unique = nonEmpty.length > 0 && new Set(nonEmpty).size === nonEmpty.length
    const nullable = values.some((v) => v === '')
    const type = inferType(values)
    const out: SyntheticDataColumn = {
      id: `csv-col-${Date.now()}-${idx}`,
      name,
      type,
      nullable,
      unique,
    }
    if (type === 'integer' || type === 'number') {
      const nums = nonEmpty.map((v) => Number(v)).filter((v) => Number.isFinite(v))
      if (nums.length) {
        out.min = Math.min(...nums)
        out.max = Math.max(...nums)
      }
    }
    if (type === 'category') out.values = Array.from(new Set(nonEmpty)).join(',')
    return out
  })
}
