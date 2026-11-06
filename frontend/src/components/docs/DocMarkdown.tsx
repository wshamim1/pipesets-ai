/**
 * Markdown for the in-app user guide (Docs). Covers what docs/guide/*.md uses: headings with
 * GitHub-style anchors, paragraphs, nested lists with code blocks and paragraphs inside items,
 * tables, fenced code, blockquotes, rules, and inline code / bold / italic / links.
 *
 * Links: another guide ("03-tools.md#x") or a section ("#x") navigates inside Docs; http(s) opens in
 * a new tab; anything else points at a file in the repository and is shown as plain text.
 */
import React from 'react'
import { headingAnchors } from '../../utils/guides'
import { classifyLink, docHref, tableCells } from '../../utils/docLinks'
import { DocDiagram } from './DocDiagram'

interface Ctx {
  anchors: string[]
  next: number
  onNavigate: (page: string | null, anchor: string) => void
}

// ── Inline ────────────────────────────────────────────────────────────────────

const INLINE = /(`[^`]+`)|\[([^\]]+)\]\(([^)\s]+)\)|\*\*(.+?)\*\*|\*([^*\s][^*]*?)\*/g

function inline(text: string, ctx: Ctx, key = 'i'): React.ReactNode[] {
  const out: React.ReactNode[] = []
  let last = 0
  let n = 0
  for (const m of text.matchAll(INLINE)) {
    if (m.index! > last) out.push(text.slice(last, m.index))
    const k = `${key}-${n++}`
    if (m[1]) out.push(<code key={k}>{m[1].slice(1, -1)}</code>)
    else if (m[2] !== undefined) out.push(<DocLink key={k} href={m[3]} ctx={ctx}>{inline(m[2], ctx, k)}</DocLink>)
    else if (m[4] !== undefined) out.push(<strong key={k}>{inline(m[4], ctx, k)}</strong>)
    else if (m[5] !== undefined) out.push(<em key={k}>{inline(m[5], ctx, k)}</em>)
    last = m.index! + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

function DocLink({ href, ctx, children }: { href: string; ctx: Ctx; children: React.ReactNode }) {
  const target = classifyLink(href)
  if (target.kind === 'external')
    return <a href={target.href} target="_blank" rel="noopener noreferrer">{children}</a>
  if (target.kind === 'repo')
    return <span className="doc-repo-link" title={`In the Pipesets repository: ${target.path}`}>{children}</span>
  const page = target.kind === 'guide' ? target.page : null
  const href2 = target.kind === 'guide' ? docHref(target.page, target.anchor) : `#${target.anchor}`
  return (
    <a
      href={href2}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return   // let "open in new tab" work
        e.preventDefault()
        ctx.onNavigate(page, target.anchor)
      }}
    >{children}</a>
  )
}

// ── Blocks ────────────────────────────────────────────────────────────────────

const indentOf = (line: string) => line.length - line.trimStart().length
const FENCE = /^\s*```/
const HEADING = /^(#{1,4})\s+(.+?)\s*#*$/
const LIST_ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/
const RULE = /^\s*---+\s*$/
const isTableStart = (lines: string[], i: number) =>
  lines[i].trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])
const startsBlock = (lines: string[], i: number) =>
  FENCE.test(lines[i]) || HEADING.test(lines[i]) || LIST_ITEM.test(lines[i]) || RULE.test(lines[i])
  || lines[i].trimStart().startsWith('>') || isTableStart(lines, i)

function blocks(lines: string[], ctx: Ctx, key = 'b'): React.ReactNode[] {
  const out: React.ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const k = `${key}-${i}`
    if (!line.trim()) { i++; continue }

    if (FENCE.test(line)) {
      const indent = indentOf(line)
      const lang = line.trim().slice(3).trim()
      const code: string[] = []
      i++
      while (i < lines.length && !FENCE.test(lines[i])) {
        code.push(lines[i].slice(Math.min(indent, indentOf(lines[i]))))
        i++
      }
      i++
      out.push(lang === 'mermaid'
        ? <DocDiagram key={k} source={code.join('\n')} />
        : <pre key={k} className="doc-code" data-lang={lang || undefined}><code>{code.join('\n')}</code></pre>)
      continue
    }

    const h = line.match(HEADING)
    if (h) {
      const level = h[1].length as 1 | 2 | 3 | 4
      const Tag = `h${level}` as const
      const id = ctx.anchors[ctx.next++]
      out.push(
        <Tag key={k} id={id} className="doc-heading">
          {inline(h[2], ctx, k)}
          {level > 1 && id && (
            <a className="doc-anchor" href={`#${id}`} aria-label="Link to this section"
              onClick={(e) => { e.preventDefault(); ctx.onNavigate(null, id) }}>#</a>
          )}
        </Tag>,
      )
      i++
      continue
    }

    if (RULE.test(line)) { out.push(<hr key={k} />); i++; continue }

    if (line.trimStart().startsWith('>')) {
      const quote: string[] = []
      while (i < lines.length && lines[i].trimStart().startsWith('>')) {
        quote.push(lines[i].trimStart().replace(/^>\s?/, ''))
        i++
      }
      out.push(<blockquote key={k}>{blocks(quote, ctx, k)}</blockquote>)
      continue
    }

    if (isTableStart(lines, i)) {
      const head = tableCells(lines[i])
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(tableCells(lines[i++]))
      out.push(
        <div key={k} className="doc-table-wrap">
          <table>
            <thead><tr>{head.map((c, ci) => <th key={ci}>{inline(c, ctx, `${k}-h${ci}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => (
              <tr key={ri}>{head.map((_, ci) => <td key={ci}>{inline(r[ci] ?? '', ctx, `${k}-${ri}-${ci}`)}</td>)}</tr>
            ))}</tbody>
          </table>
        </div>,
      )
      continue
    }

    if (LIST_ITEM.test(line)) {
      const [node, next] = list(lines, i, ctx, k)
      out.push(node)
      i = next
      continue
    }

    const para: string[] = [line.trim()]
    i++
    while (i < lines.length && lines[i].trim() && !startsBlock(lines, i)) para.push(lines[i++].trim())
    out.push(<p key={k}>{inline(para.join(' '), ctx, k)}</p>)
  }
  return out
}

function list(lines: string[], start: number, ctx: Ctx, key: string): [React.ReactNode, number] {
  const first = lines[start].match(LIST_ITEM)!
  const indent = first[1].length
  const ordered = /\d/.test(first[2])
  const items: React.ReactNode[] = []
  let i = start
  while (i < lines.length) {
    const m = lines[i].match(LIST_ITEM)
    if (!m || m[1].length !== indent || /\d/.test(m[2]) !== ordered) break
    // Lines indented at least as far as the item's text belong to the item ("1. Text" → 3, "- Text" → 2)
    const contentIndent = m[3] ? lines[i].indexOf(m[3], indent + m[2].length) : indent + m[2].length + 1
    const item: string[] = [m[3]]
    i++
    while (i < lines.length) {
      const line = lines[i]
      if (!line.trim()) {
        let j = i + 1
        while (j < lines.length && !lines[j].trim()) j++
        if (j < lines.length && indentOf(lines[j]) >= contentIndent) { item.push(''); i++; continue }
        break
      }
      if (indentOf(line) >= contentIndent) { item.push(line.slice(contentIndent)); i++; continue }
      const marker = line.match(LIST_ITEM)
      if (marker && marker[1].length <= indent) break
      if (marker || startsBlock(lines, i) || !item[item.length - 1]?.trim()) break
      item.push(line.trim())   // lazy continuation of the item's paragraph
      i++
    }
    const k = `${key}-li${items.length}`
    const body = blocks(item, ctx, k)
    items.push(<li key={k}>{body}</li>)
    // Blank lines between items of the same list
    let j = i
    while (j < lines.length && !lines[j].trim()) j++
    const nextItem = j < lines.length ? lines[j].match(LIST_ITEM) : null
    if (j > i && nextItem && nextItem[1].length === indent && /\d/.test(nextItem[2]) === ordered) i = j
  }
  const startNo = ordered ? parseInt(first[2], 10) : undefined
  const node = ordered
    ? <ol key={key} start={startNo !== 1 ? startNo : undefined}>{items}</ol>
    : <ul key={key}>{items}</ul>
  return [node, i]
}

export function DocMarkdown({ body, onNavigate }: { body: string; onNavigate: Ctx['onNavigate'] }) {
  const ctx: Ctx = { anchors: headingAnchors(body).map((h) => h.anchor), next: 0, onNavigate }
  return <div className="doc-markdown">{blocks(body.split('\n'), ctx)}</div>
}
