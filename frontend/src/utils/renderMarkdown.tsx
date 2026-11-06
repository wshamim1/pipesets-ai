/**
 * renderMarkdown — React rendering helpers for inline markdown and block content.
 */
import React from 'react'
import type { OutputFormat } from './contentFormats'

// ── Inline span renderer (bold, italic, inline code) ─────────────────────────

export function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**'))
      return <strong key={i}>{part.slice(2, -2)}</strong>
    if (part.startsWith('*') && part.endsWith('*'))
      return <em key={i}>{part.slice(1, -1)}</em>
    if (part.startsWith('`') && part.endsWith('`'))
      return <code key={i} style={{ background: '#f1f5f9', borderRadius: 3, padding: '1px 4px', fontSize: '0.9em', fontFamily: 'monospace' }}>{part.slice(1, -1)}</code>
    return part
  })
}

// ── Full markdown block renderer ──────────────────────────────────────────────

export function renderMarkdownBlock(content: string): React.ReactNode {
  const lines = content.split('\n')
  const result: React.ReactNode[] = []
  let i = 0

  const cellStyle: React.CSSProperties = { border: '1px solid #e2e8f0', padding: '5px 10px', textAlign: 'left' }
  const thStyle: React.CSSProperties = { ...cellStyle, background: '#f1f5f9', fontWeight: 700, whiteSpace: 'nowrap' }

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Heading
    const hMatch = trimmed.match(/^(#{1,3})\s+(.+)/)
    if (hMatch) {
      const level = hMatch[1].length
      const sizes = ['1.1em', '1em', '0.95em']
      result.push(<div key={i} style={{ fontWeight: 700, fontSize: sizes[level - 1], marginTop: level === 1 ? 10 : 6, marginBottom: 2 }}>{renderInline(hMatch[2])}</div>)
      i++; continue
    }

    // Markdown table
    if (trimmed.startsWith('|') && i + 1 < lines.length && lines[i + 1].trim().match(/^\|[-| ]+\|$/)) {
      const headerCells = trimmed.split('|').map(c => c.trim()).filter(Boolean)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(lines[i].trim().split('|').map(c => c.trim()).filter(Boolean))
        i++
      }
      result.push(
        <div key={`tbl-${i}`} style={{ overflowX: 'auto', margin: '6px 0' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 12 }}>
            <thead><tr>{headerCells.map((h, ci) => <th key={ci} style={thStyle}>{renderInline(h)}</th>)}</tr></thead>
            <tbody>{rows.map((row, ri) => (
              <tr key={ri} style={{ background: ri % 2 === 0 ? '#fff' : '#f8fafc' }}>
                {row.map((cell, ci) => <td key={ci} style={cellStyle}>{renderInline(cell)}</td>)}
              </tr>
            ))}</tbody>
          </table>
        </div>
      )
      continue
    }

    // Fenced code block
    if (trimmed.startsWith('```')) {
      const lang = trimmed.slice(3).trim()
      i++
      const codeLines: string[] = []
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      i++
      result.push(
        <pre key={`code-${i}`} style={{ background: '#0f172a', color: '#e2e8f0', borderRadius: 6, padding: '10px 12px', fontSize: 12, overflowX: 'auto', margin: '6px 0', fontFamily: 'monospace' }}>
          {lang && <span style={{ color: '#94a3b8', fontSize: 10, display: 'block', marginBottom: 4 }}>{lang}</span>}
          {codeLines.join('\n')}
        </pre>
      )
      continue
    }

    // Unordered list
    if (trimmed.match(/^[-•*]\s+/)) {
      const items: string[] = []
      while (i < lines.length && lines[i].trim().match(/^[-•*]\s+/)) {
        items.push(lines[i].trim().replace(/^[-•*]\s+/, ''))
        i++
      }
      result.push(
        <ul key={`ul-${i}`} style={{ margin: '4px 0', paddingLeft: 20 }}>
          {items.map((item, li) => <li key={li} style={{ marginBottom: 2, lineHeight: 1.5 }}>{renderInline(item)}</li>)}
        </ul>
      )
      continue
    }

    // Numbered list
    if (trimmed.match(/^\d+\.\s+/)) {
      const items: string[] = []
      while (i < lines.length && lines[i].trim().match(/^\d+\.\s+/)) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''))
        i++
      }
      result.push(
        <ol key={`ol-${i}`} style={{ margin: '4px 0', paddingLeft: 20 }}>
          {items.map((item, li) => <li key={li} style={{ marginBottom: 2, lineHeight: 1.5 }}>{renderInline(item)}</li>)}
        </ol>
      )
      continue
    }

    // Horizontal rule
    if (trimmed.match(/^---+$/)) {
      result.push(<hr key={i} style={{ border: 'none', borderTop: '1px solid #e2e8f0', margin: '8px 0' }} />)
      i++; continue
    }

    // Blank line
    if (!trimmed) {
      result.push(<div key={i} style={{ height: 6 }} />)
      i++; continue
    }

    // Normal paragraph
    result.push(<div key={i} style={{ lineHeight: 1.6 }}>{renderInline(trimmed)}</div>)
    i++
  }

  return <div style={{ fontSize: 13 }}>{result}</div>
}

// ── Smart content renderer (picks rendering strategy based on format) ─────────

export function renderContent(content: string, format: OutputFormat): React.ReactNode {
  if (!content) return null

  if (format === 'json' || format === 'pydantic' || (format === 'auto' && content.trimStart().match(/^[{\[]/))) {
    try {
      const parsed = JSON.parse(content.trim())
      return (
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 12, fontFamily: 'monospace', color: '#0f766e', background: '#f0fdf4', borderRadius: 6, padding: '8px 10px' }}>
          {JSON.stringify(parsed, null, 2)}
        </pre>
      )
    } catch { /* fall through */ }
  }

  if (format === 'html') {
    return (
      <div style={{ border: '1px solid #e2e8f0', borderRadius: 6, overflow: 'hidden' }}>
        <div style={{ background: '#f1f5f9', borderBottom: '1px solid #e2e8f0', padding: '3px 10px', fontSize: 10, color: '#64748b', fontFamily: 'monospace' }}>
          &lt;h&gt; HTML Preview
        </div>
        <iframe
          srcDoc={content}
          sandbox="allow-scripts"
          style={{ width: '100%', minHeight: 200, border: 'none', display: 'block', background: '#fff' }}
          title="HTML output preview"
        />
      </div>
    )
  }

  if (format === 'xml' || (format === 'auto' && content.trimStart().startsWith('<') && content.includes('</'))) {
    return (
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: 12, fontFamily: 'monospace', color: '#7c3aed', background: '#faf5ff', borderRadius: 6, padding: '8px 10px' }}>
        {content}
      </pre>
    )
  }

  if (format === 'csv') {
    const lines = content.trim().split('\n').filter(Boolean)
    if (lines.length >= 2) {
      const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''))
      const rows = lines.slice(1).map(l => l.split(',').map(c => c.trim().replace(/^"|"$/g, '')))
      return (
        <div style={{ overflowX: 'auto', fontSize: 12 }}>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr>{headers.map((h, i) => (
                <th key={i} style={{ background: '#f1f5f9', border: '1px solid #e2e8f0', padding: '5px 10px', textAlign: 'left', fontWeight: 700, whiteSpace: 'nowrap' }}>{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr key={ri} style={{ background: ri % 2 === 0 ? '#fff' : '#f8fafc' }}>
                  {row.map((cell, ci) => (
                    <td key={ci} style={{ border: '1px solid #e2e8f0', padding: '5px 10px' }}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
    }
  }

  return renderMarkdownBlock(content)
}
