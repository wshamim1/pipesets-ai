import type { SyntheticDataColumn } from '../types'

function splitCategoryValues(values?: string): string[] {
  return String(values || '')
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean)
}

export function columnsToJsonSchema(columns: SyntheticDataColumn[]): string {
  const properties: Record<string, Record<string, unknown>> = {}
  const required: string[] = []

  for (const col of columns) {
    const name = String(col.name || '').trim()
    if (!name) continue

    let baseType: 'string' | 'integer' | 'number' | 'boolean' = 'string'
    let format: string | undefined
    if (col.type === 'integer') baseType = 'integer'
    else if (col.type === 'number') baseType = 'number'
    else if (col.type === 'boolean') baseType = 'boolean'
    else if (col.type === 'date') format = 'date'
    else if (col.type === 'datetime') format = 'date-time'
    else if (col.type === 'email') format = 'email'
    else if (col.type === 'uuid') format = 'uuid'

    const spec: Record<string, unknown> = { type: col.nullable ? [baseType, 'null'] : baseType }
    if (format && baseType === 'string') spec.format = format
    if (baseType === 'number' || baseType === 'integer') {
      if (typeof col.min === 'number') spec.minimum = col.min
      if (typeof col.max === 'number') spec.maximum = col.max
    }
    if (col.type === 'category') {
      const values = splitCategoryValues(col.values)
      if (values.length) spec.enum = values
    }
    properties[name] = spec
    if (!col.nullable) required.push(name)
  }

  return JSON.stringify({
    type: 'object',
    properties,
    required,
    additionalProperties: false,
  }, null, 2)
}
