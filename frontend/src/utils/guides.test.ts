import { describe, expect, it } from 'vitest'
import { GUIDES, buildGuides, findGuide, headingAnchors, searchGuides, slugify } from './guides'
import { classifyLink } from './docLinks'

describe('the bundled user guide', () => {
  it('includes every guide in docs/guide, overview first, in number order', () => {
    const ids = GUIDES.map((g) => g.id)
    expect(ids[0]).toBe('index')
    expect(ids).toContain('03-tools')
    expect(ids).toContain('12-document-extraction')
    expect(ids.indexOf('10-share-integrate')).toBeGreaterThan(ids.indexOf('09-monitor-automate'))
    expect(findGuide('03-tools')?.title).toBe('3. Tools')
    expect(findGuide('nope')?.id).toBe('index')
  })

  it('has no broken links between guides or to sections', () => {
    const anchors = new Map(GUIDES.map((g) => [g.id, new Set(headingAnchors(g.body).map((h) => h.anchor))]))
    const broken: string[] = []
    for (const g of GUIDES) {
      for (const m of g.body.matchAll(/\]\(([^)\s]+)\)/g)) {
        const t = classifyLink(m[1])
        if (t.kind === 'guide' && (!anchors.has(t.page) || (t.anchor && !anchors.get(t.page)!.has(t.anchor))))
          broken.push(`${g.id} → ${m[1]}`)
        if (t.kind === 'anchor' && !anchors.get(g.id)!.has(t.anchor)) broken.push(`${g.id} → ${m[1]}`)
      }
    }
    expect(broken).toEqual([])
  })

  it('every "?" help link in the app points at a section that exists', () => {
    const sources = import.meta.glob('../components/**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
    const links = Object.entries(sources).flatMap(([file, src]) =>
      [...src.matchAll(/<HelpLink page="([^"]+)"(?: section="([^"]*)")?/g)].map((m) => ({ file, page: m[1], section: m[2] ?? '' })))
    expect(links.length).toBeGreaterThanOrEqual(11)
    const missing = links.filter(({ page, section }) => {
      const g = GUIDES.find((x) => x.id === page)
      return !g || (section && !headingAnchors(g.body).some((h) => h.anchor === section))
    })
    expect(missing).toEqual([])
  })
})

describe('guides helpers', () => {
  it('makes GitHub-style anchors, numbering repeats and skipping code blocks', () => {
    expect(slugify('2. OCR for scanned pages')).toBe('2-ocr-for-scanned-pages')
    expect(slugify('REST API (`/v1`)')).toBe('rest-api-v1')
    expect(slugify('Drafts, versions and publishing')).toBe('drafts-versions-and-publishing')
    const body = '# T\n## Setup\n```bash\n# not a heading\n```\n## Setup\n### Run it'
    expect(headingAnchors(body).map((h) => h.anchor)).toEqual(['t', 'setup', 'setup-1', 'run-it'])
  })

  it('searches sections, heading matches first', () => {
    const guides = buildGuides({
      'x/README.md': '# Guide\nWelcome.',
      'x/02-b.md': '# 2. B\n## Webhooks\nStart a pipeline from another system.\n## Other\nMentions webhooks once.',
      'x/01-a.md': '# 1. A\n## Intro\nNothing here.',
    })
    expect(guides.map((g) => g.id)).toEqual(['index', '01-a', '02-b'])
    const hits = searchGuides('webhooks', guides)
    expect(hits.map((h) => [h.guide.id, h.anchor])).toEqual([['02-b', 'webhooks'], ['02-b', 'other']])
    expect(hits[1].snippet).toContain('Mentions webhooks once.')
    expect(searchGuides('webhooks pipeline', guides).map((h) => h.anchor)).toEqual(['webhooks'])
    expect(searchGuides(' ', guides)).toEqual([])
  })
})
