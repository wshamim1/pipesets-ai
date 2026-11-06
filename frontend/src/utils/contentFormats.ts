/**
 * contentFormats — output format types, constants, and the convertContent utility.
 * These are pure data-transform functions — no React imports needed.
 */

export type OutputFormat = 'auto' | 'table' | 'json' | 'pydantic' | 'xml' | 'html' | 'markdown' | 'csv' | 'bullets'

export const FORMAT_OPTIONS: { value: OutputFormat; label: string; icon: string }[] = [
  { value: 'auto',     label: 'Auto',     icon: '✨' },
  { value: 'table',    label: 'Table',    icon: '📊' },
  { value: 'json',     label: 'JSON',     icon: '{ }' },
  { value: 'pydantic', label: 'Pydantic', icon: '🐍' },
  { value: 'xml',      label: 'XML',      icon: '</>' },
  { value: 'html',     label: 'HTML',     icon: '<h>' },
  { value: 'markdown', label: 'Markdown', icon: '# M' },
  { value: 'csv',      label: 'CSV',      icon: '📄' },
  { value: 'bullets',  label: 'Bullets',  icon: '• •' },
]

export const FORMAT_SUFFIXES: Record<OutputFormat, string> = {
  auto:     '',
  table:    '\n\nIMPORTANT: Format your response as a markdown table using | and - characters. Use a header row.',
  json:     '\n\nIMPORTANT: Respond ONLY with valid JSON. No explanation, no markdown fences, just raw JSON.',
  pydantic: '\n\nIMPORTANT: Respond ONLY with valid JSON. No explanation, no markdown fences, just raw JSON.',
  xml:      '\n\nIMPORTANT: Respond ONLY with valid XML. Start with a root element, no preamble or explanation.',
  html:     '\n\nIMPORTANT: Respond ONLY with valid HTML. Output a complete, well-formed HTML fragment or full document. No explanation outside the HTML.',
  markdown: '\n\nIMPORTANT: Use rich Markdown formatting — headings, bold, bullet lists, code blocks where appropriate.',
  csv:      '\n\nIMPORTANT: Respond ONLY with CSV data. First row must be the header. Use commas as delimiters. No explanation.',
  bullets:  '\n\nIMPORTANT: Respond as a concise bullet-point list. Each bullet on its own line starting with •. No prose.',
}

// ── Client-side content converter ────────────────────────────────────────────

interface Row { [col: string]: string }

function parseToRows(trimmed: string): { headers: string[]; rows: Row[] } | null {
  // 1. JSON array of objects
  try {
    const parsed = JSON.parse(trimmed)
    if (Array.isArray(parsed) && parsed.length > 0 && typeof parsed[0] === 'object') {
      const headers = Object.keys(parsed[0])
      return {
        headers,
        rows: parsed.map((r: Record<string, unknown>) => {
          const row: Row = {}
          headers.forEach(h => { row[h] = String(r[h] ?? '') })
          return row
        }),
      }
    }
  } catch { /* not JSON */ }

  // 2. Markdown table
  const lines = trimmed.split('\n')
  const pipeLines = lines.filter(l => l.trim().startsWith('|'))
  if (pipeLines.length >= 2) {
    const headers = pipeLines[0].split('|').map(c => c.trim()).filter(Boolean)
    const dataLines = pipeLines.slice(2)
    if (headers.length > 0 && dataLines.length > 0) {
      const rows: Row[] = dataLines.map(l => {
        const cells = l.split('|').map(c => c.trim()).filter(Boolean)
        const row: Row = {}
        headers.forEach((h, i) => { row[h] = cells[i] ?? '' })
        return row
      }).filter(r => Object.values(r).some(v => v))
      return { headers, rows }
    }
  }

  // 3. CSV
  const csvLines = trimmed.split('\n').filter(Boolean)
  if (csvLines.length >= 2 && csvLines[0].includes(',') && !csvLines[0].includes('|')) {
    const headers = csvLines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''))
    const rows: Row[] = csvLines.slice(1).map(l => {
      const cells = l.split(',').map(c => c.trim().replace(/^"|"$/g, ''))
      const row: Row = {}
      headers.forEach((h, i) => { row[h] = cells[i] ?? '' })
      return row
    })
    return { headers, rows }
  }

  // 4. Bullet/numbered list → single-column
  const bulletLines = trimmed.split('\n').filter(l => l.trim().match(/^[-•*\d.]\s+/))
  if (bulletLines.length >= 2) {
    const rows: Row[] = bulletLines.map(l => ({
      Item: l.trim().replace(/^[-•*]|\d+\.\s*/g, '').trim(),
    }))
    return { headers: ['Item'], rows }
  }

  return null
}

export function convertContent(raw: string, targetFormat: OutputFormat): string {
  if (targetFormat === 'auto') return raw

  // pydantic produces JSON — treat identically to 'json' for display purposes
  // html is returned as-is (rendered by the caller)
  const effectiveFormat = targetFormat === 'pydantic' ? 'json' : targetFormat

  if (effectiveFormat === 'html') {
    // Strip markdown code fences if the LLM wrapped the HTML in ```html ... ```
    const fenceMatch = raw.trim().match(/^```(?:html)?\s*([\s\S]*?)```\s*$/i)
    return fenceMatch ? fenceMatch[1].trim() : raw.trim()
  }

  const trimmed = raw.trim()
  const parsed = parseToRows(trimmed)

  if (effectiveFormat === 'table') {
    if (!parsed) return raw
    const { headers, rows } = parsed
    const sep = headers.map(() => '---').join(' | ')
    const headerRow = headers.join(' | ')
    const dataRows = rows.map(r => headers.map(h => r[h] ?? '').join(' | '))
    return `| ${headerRow} |\n| ${sep} |\n${dataRows.map(r => `| ${r} |`).join('\n')}`
  }

  if (effectiveFormat === 'json') {
    if (!parsed) {
      try { return JSON.stringify(JSON.parse(trimmed), null, 2) } catch { return raw }
    }
    return JSON.stringify(parsed.rows, null, 2)
  }

  if (effectiveFormat === 'csv') {
    if (!parsed) return raw
    const { headers, rows } = parsed
    const escape = (v: string) => v.includes(',') ? `"${v}"` : v
    return [
      headers.map(escape).join(','),
      ...rows.map(r => headers.map(h => escape(r[h] ?? '')).join(',')),
    ].join('\n')
  }

  if (effectiveFormat === 'xml') {
    if (!parsed) return raw
    const { rows } = parsed
    const toTag = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '_').replace(/^_+/, '') || 'field'
    const inner = rows.map((r, i) => {
      const fields = Object.entries(r).map(([k, v]) => `    <${toTag(k)}>${v}</${toTag(k)}>`).join('\n')
      return `  <row index="${i + 1}">\n${fields}\n  </row>`
    }).join('\n')
    return `<results>\n${inner}\n</results>`
  }

  if (effectiveFormat === 'bullets') {
    if (!parsed) return raw
    const { headers, rows } = parsed
    return rows.map((r, i) => {
      const fields = headers.map(h => `  - **${h}:** ${r[h]}`).join('\n')
      return `• Row ${i + 1}\n${fields}`
    }).join('\n')
  }

  // markdown — return as-is
  return raw
}
