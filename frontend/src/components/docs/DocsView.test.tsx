import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DocMarkdown } from './DocMarkdown'
import { classifyLink, tableCells, OPEN_DOCS_EVENT } from '../../utils/docLinks'
import { DocsView } from './DocsView'
import { HelpLink } from './HelpLink'
import { GUIDES, buildGuides } from '../../utils/guides'

const md = (body: string, onNavigate = vi.fn()) => {
  const view = render(<DocMarkdown body={body} onNavigate={onNavigate} />)
  return { ...view, onNavigate }
}

describe('DocMarkdown', () => {
  it('renders headings with anchors, paragraphs, quotes, rules and inline styles', () => {
    const { container } = md('# Title\n\nSome **bold**, *italic* and `code`\ncontinued.\n\n> A note\n\n---\n\n## Two words')
    expect(container.querySelector('h1')!.id).toBe('title')
    expect(container.querySelector('h2')!.id).toBe('two-words')
    const p = container.querySelector('p')!
    expect(p.textContent).toBe('Some bold, italic and code continued.')
    expect(p.querySelector('strong')!.textContent).toBe('bold')
    expect(p.querySelector('em')!.textContent).toBe('italic')
    expect(p.querySelector('code')!.textContent).toBe('code')
    expect(container.querySelector('blockquote')!.textContent).toBe('A note')
    expect(container.querySelector('hr')).toBeTruthy()
  })

  it('renders nested lists with code blocks and paragraphs inside items', () => {
    const { container } = md([
      '1. First step',
      '2. Second step:',
      '',
      '   ```bash',
      '   pip install x',
      '   ```',
      '',
      '   - nested a',
      '   - nested b',
      '     continued',
      '3. Third',
      '',
      'After.',
    ].join('\n'))
    const ol = container.querySelector('ol')!
    expect(ol.children).toHaveLength(3)
    expect(ol.children[1].querySelector('pre')!.textContent).toBe('pip install x')
    expect(ol.children[1].querySelectorAll('ul > li')).toHaveLength(2)
    expect(ol.children[1].querySelectorAll('ul > li')[1].textContent).toBe('nested b continued')
    expect(container.querySelector('ol + p')!.textContent).toBe('After.')
  })

  it('renders tables, keeping | inside code', () => {
    expect(tableCells('| `a|b` | c \\| d |')).toEqual(['`a|b`', 'c | d'])
    const { container } = md('| A | B |\n|---|---|\n| `x` | **y** |\n| only one |')
    expect([...container.querySelectorAll('th')].map((c) => c.textContent)).toEqual(['A', 'B'])
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
    expect(container.querySelector('td code')!.textContent).toBe('x')
  })

  it('routes links: guides and sections in-app, web in a new tab, repo files as text', () => {
    expect(classifyLink('03-tools.md#custom-tools')).toEqual({ kind: 'guide', page: '03-tools', anchor: 'custom-tools' })
    expect(classifyLink('README.md')).toEqual({ kind: 'guide', page: 'index', anchor: '' })
    expect(classifyLink('../../sdk/README.md')).toEqual({ kind: 'repo', path: 'sdk/README.md' })
    const { container, onNavigate } = md('[Tools](03-tools.md#custom-tools), [here](#setup), [MCP](https://modelcontextprotocol.io), [SDK](../../sdk/README.md)')
    const [tools, here, web] = container.querySelectorAll('a')
    expect(tools.getAttribute('href')).toBe('?view=docs&page=03-tools#custom-tools')
    fireEvent.click(tools)
    expect(onNavigate).toHaveBeenCalledWith('03-tools', 'custom-tools')
    fireEvent.click(here)
    expect(onNavigate).toHaveBeenCalledWith(null, 'setup')
    expect(web.getAttribute('target')).toBe('_blank')
    expect(screen.getByText('SDK').tagName).toBe('SPAN')
  })

  it('renders every real guide', () => {
    for (const g of GUIDES) {
      const { container, unmount } = md(g.body)
      expect(container.querySelector('h1'), g.id).toBeTruthy()
      expect(container.textContent).not.toContain('```')
      unmount()
    }
  })
})

const GUIDE_SET = buildGuides({
  'd/README.md': '# Guide\n\nStart with [Tools](02-tools.md#custom-tools).',
  'd/02-tools.md': '# 2. Tools\n\n## Built-in\nUse them.\n\n## Custom tools\nWrite one with webhooks.',
})

describe('DocsView', () => {
  it('lists guides, opens the one in the URL, and navigates between them', () => {
    const onPageChange = vi.fn()
    const { rerender } = render(<DocsView page={null} onPageChange={onPageChange} guides={GUIDE_SET} />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Guide')
    fireEvent.click(screen.getByText('Tools'))
    expect(onPageChange).toHaveBeenCalledWith('02-tools')
    expect(window.location.hash).toBe('#custom-tools')

    rerender(<DocsView page="02-tools" onPageChange={onPageChange} guides={GUIDE_SET} />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('2. Tools')
    expect(screen.getByLabelText('On this page').textContent).toContain('Custom tools')
    expect(screen.getByText('2. Tools', { selector: 'nav a' }).getAttribute('aria-current')).toBe('page')
  })

  it('searches across guides and opens a result', () => {
    const onPageChange = vi.fn()
    render(<DocsView page="index" onPageChange={onPageChange} guides={GUIDE_SET} />)
    fireEvent.change(screen.getByLabelText('Search the docs'), { target: { value: 'webhooks' } })
    const hit = screen.getByText('Custom tools', { selector: '.docs-hit-title' })
    fireEvent.click(hit)
    expect(onPageChange).toHaveBeenCalledWith('02-tools')
    expect(screen.queryByLabelText('Search results')).toBeNull()

    fireEvent.change(screen.getByLabelText('Search the docs'), { target: { value: 'zebra' } })
    expect(screen.getByText(/Nothing found/)).toBeTruthy()
  })

  it('says so when the build has no guides', () => {
    render(<DocsView page={null} onPageChange={vi.fn()} guides={[]} />)
    expect(screen.getByText(/wasn't included in this build/)).toBeTruthy()
  })
})

describe('HelpLink', () => {
  it('asks the app to open Docs at a section, or opens a new tab with Cmd/Ctrl', () => {
    const seen = vi.fn()
    window.addEventListener(OPEN_DOCS_EVENT, (e) => seen((e as CustomEvent).detail))
    render(<HelpLink page="07-guardrails-budgets" section="budgets" label="About budgets" />)
    const link = screen.getByLabelText('About budgets')
    expect(link.getAttribute('href')).toBe('?view=docs&page=07-guardrails-budgets#budgets')
    fireEvent.click(link)
    expect(seen).toHaveBeenCalledWith({ page: '07-guardrails-budgets', section: 'budgets' })
    seen.mockClear()
    fireEvent.click(link, { metaKey: true })
    expect(seen).not.toHaveBeenCalled()
  })
})
