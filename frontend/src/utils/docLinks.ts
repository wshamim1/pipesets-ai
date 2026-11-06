/** Links in the in-app user guide (Docs): where a Markdown link goes, URLs for a guide section, and
 * the event "?" help links send to open Docs (App listens for it). */

export type LinkTarget =
  | { kind: 'guide'; page: string; anchor: string }
  | { kind: 'anchor'; anchor: string }
  | { kind: 'external'; href: string }
  | { kind: 'repo'; path: string }

export function classifyLink(href: string): LinkTarget {
  if (/^(https?:|mailto:)/i.test(href)) return { kind: 'external', href }
  if (href.startsWith('#')) return { kind: 'anchor', anchor: href.slice(1) }
  const m = href.match(/^(?:\.\/)?([\w-]+)\.md(?:#(.*))?$/)
  if (m) return { kind: 'guide', page: m[1].toLowerCase() === 'readme' ? 'index' : m[1], anchor: m[2] ?? '' }
  return { kind: 'repo', path: href.replace(/^(\.\.\/)+/, '') }
}

export const docHref = (page: string, anchor = '') =>
  `?view=docs&page=${encodeURIComponent(page)}${anchor ? `#${anchor}` : ''}`

/** Cells of a table row, not splitting on "|" inside `code` or escaped as "\|". */
export function tableCells(row: string): string[] {
  const cells: string[] = []
  let cur = ''
  let inCode = false
  const s = row.trim().replace(/^\|/, '').replace(/\|$/, '')
  for (let i = 0; i < s.length; i++) {
    const c = s[i]
    if (c === '\\' && s[i + 1] === '|') { cur += '|'; i++; continue }
    if (c === '`') inCode = !inCode
    if (c === '|' && !inCode) { cells.push(cur.trim()); cur = ''; continue }
    cur += c
  }
  cells.push(cur.trim())
  return cells
}

export const OPEN_DOCS_EVENT = 'pipesets:open-docs'

export interface OpenDocsDetail { page: string; section: string }

export function openDocs(page: string, section = '') {
  window.dispatchEvent(new CustomEvent<OpenDocsDetail>(OPEN_DOCS_EVENT, { detail: { page, section } }))
}
