/**
 * The user guide shown in Docs: the Markdown files in the repo's docs/guide/, bundled at build time,
 * so the docs always match the version that's running. Docker builds get that folder as the extra
 * build context "docs" (frontend/Dockerfile).
 */

export interface Guide {
  /** File name without .md ("03-tools"); the overview (README.md) is "index" */
  id: string
  title: string
  body: string
}

export interface SearchHit {
  guide: Guide
  heading: string
  anchor: string
  snippet: string
}

const files = import.meta.glob('../../../docs/guide/*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

/** GitHub-style heading anchor: "2. OCR for scanned pages" → "2-ocr-for-scanned-pages" */
export function slugify(heading: string): string {
  return heading
    .replace(/`/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .toLowerCase()
    .trim()
    .replace(/[^\p{L}\p{N}_\- ]/gu, '')
    .replace(/ /g, '-')
}

export interface Heading { level: number; text: string; anchor: string }

/** A document cut at its headings (not at "#" lines inside code blocks). The first section is the
 * text before the first heading (heading null). Anchors repeat GitHub's "-1", "-2" for duplicates. */
export function sections(body: string): { heading: Heading | null; text: string }[] {
  const seen = new Map<string, number>()
  const out: { heading: Heading | null; lines: string[] }[] = [{ heading: null, lines: [] }]
  let inCode = false
  for (const line of body.split('\n')) {
    if (line.trim().startsWith('```')) inCode = !inCode
    const m = !inCode && line.match(/^(#{1,4})\s+(.+?)\s*#*$/)
    if (!m) {
      out[out.length - 1].lines.push(line)
      continue
    }
    const base = slugify(m[2])
    const n = seen.get(base) ?? 0
    seen.set(base, n + 1)
    out.push({ heading: { level: m[1].length, text: m[2], anchor: n ? `${base}-${n}` : base }, lines: [] })
  }
  return out.map((s) => ({ heading: s.heading, text: s.lines.join('\n') }))
}

export function headingAnchors(body: string): Heading[] {
  return sections(body).flatMap((s) => (s.heading ? [s.heading] : []))
}

export function buildGuides(sources: Record<string, string>): Guide[] {
  return Object.entries(sources)
    .map(([path, body]) => {
      const file = path.split('/').pop()!.replace(/\.md$/, '')
      const id = file.toLowerCase() === 'readme' ? 'index' : file
      const h1 = body.match(/^#\s+(.+)$/m)?.[1]?.trim() ?? file
      const title = id === 'index' ? 'Overview' : h1
      return { id, title, body }
    })
    .sort((a, b) => (a.id === 'index' ? -1 : b.id === 'index' ? 1 : a.id.localeCompare(b.id, undefined, { numeric: true })))
}

export const GUIDES: Guide[] = buildGuides(files)

export function findGuide(id: string | null | undefined, guides: Guide[] = GUIDES): Guide | undefined {
  return guides.find((g) => g.id === id) ?? guides[0]
}

/** Plain text of Markdown, for search snippets. */
function plain(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[`*>#|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Sections of every guide that contain all the words of the query; heading matches first. */
export function searchGuides(query: string, guides: Guide[] = GUIDES, limit = 20): SearchHit[] {
  const words = query.toLowerCase().split(/\s+/).filter((w) => w.length > 1)
  if (!words.length) return []
  const hits: (SearchHit & { score: number })[] = []
  for (const guide of guides) {
    sections(guide.body).forEach(({ heading: head, text: raw }) => {
      const text = plain(raw)
      const heading = head ? plain(head.text) : guide.title
      const hay = `${heading} ${text}`.toLowerCase()
      if (!words.every((w) => hay.includes(w))) return
      const inHeading = words.filter((w) => heading.toLowerCase().includes(w)).length
      const at = Math.max(0, text.toLowerCase().indexOf(words[0]))
      const start = Math.max(0, at - 60)
      const snippet = (start ? '…' : '') + text.slice(start, start + 180) + (text.length > start + 180 ? '…' : '')
      hits.push({ guide, heading, anchor: head?.anchor ?? '', snippet, score: inHeading * 10 - (head?.level ?? 1) })
    })
  }
  return hits.sort((a, b) => b.score - a.score).slice(0, limit).map(({ score: _score, ...h }) => h)
}
