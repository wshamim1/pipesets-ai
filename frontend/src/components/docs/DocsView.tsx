/**
 * Docs: the user guide (docs/guide/*.md, bundled with the app — utils/guides.ts) with a guide list,
 * search across every guide, and "On this page" for the open one. The open guide is in the URL
 * (?view=docs&page=03-tools) and the section in its #hash, so any section can be linked to.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { GUIDES, findGuide, headingAnchors, searchGuides } from '../../utils/guides'
import type { Guide, GuideSection } from '../../utils/guides'
import { DocMarkdown } from './DocMarkdown'
import { docHref } from '../../utils/docLinks'
import '../../styles/docs.css'

/** The sidebar's groups, in order; the user guide has no label of its own */
const NAV_GROUPS: { section: GuideSection; label: string | null }[] = [
  { section: 'guide', label: null },
  { section: 'architecture', label: 'Architecture' },
]

interface Props {
  page: string | null
  onPageChange: (page: string) => void
  guides?: Guide[]
}

function scrollToSection(container: HTMLElement | null, anchor: string) {
  if (!container) return
  const target = anchor ? container.ownerDocument.getElementById(anchor) : null
  if (target) target.scrollIntoView?.({ block: 'start' })
  else container.scrollTop = 0
}

/** Put the section in the URL without adding a history entry (the page change adds one). */
function setHash(anchor: string) {
  const { pathname, search } = window.location
  window.history.replaceState(window.history.state, '', `${pathname}${search}${anchor ? `#${anchor}` : ''}`)
}

export function DocsView({ page, onPageChange, guides = GUIDES }: Props) {
  const guide = findGuide(page, guides)
  const [query, setQuery] = useState('')
  const articleRef = useRef<HTMLDivElement>(null)
  const hits = useMemo(() => searchGuides(query, guides), [query, guides])
  const toc = useMemo(() => (guide ? headingAnchors(guide.body).filter((h) => h.level === 2) : []), [guide])

  // On opening a guide (also Back / Forward), go to the section in the URL, or the top
  useEffect(() => {
    scrollToSection(articleRef.current, decodeURIComponent(window.location.hash.slice(1)))
  }, [guide?.id])

  const navigate = (target: string | null, anchor: string) => {
    setQuery('')
    setHash(anchor)
    if (target && target !== guide?.id) onPageChange(target)
    else scrollToSection(articleRef.current, anchor)
  }

  if (!guide) {
    return (
      <div className="docs-view docs-view--empty">
        <p>The user guide wasn't included in this build. It's in the repository under <code>docs/guide/</code>.</p>
      </div>
    )
  }

  return (
    <div className="docs-view">
      <nav className="docs-nav" aria-label="Guides">
        <input
          type="search"
          className="docs-search"
          placeholder="Search the docs…"
          aria-label="Search the docs"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {NAV_GROUPS.map(({ section, label }) => {
          const items = guides.filter((g) => (g.section ?? 'guide') === section)
          if (!items.length) return null
          return (
            <div key={section} className="docs-nav-group">
              {label && <div className="docs-nav-label">{label}</div>}
              <ul aria-label={label ?? 'User guide'}>
                {items.map((g) => (
                  <li key={g.id}>
                    <a
                      href={docHref(g.id)}
                      className={g.id === guide.id && !query ? 'active' : undefined}
                      aria-current={g.id === guide.id ? 'page' : undefined}
                      onClick={(e) => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); navigate(g.id, '') }}
                    >{g.title}</a>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </nav>

      <div className="docs-main" ref={articleRef}>
        {query.trim() ? (
          <section className="docs-results" aria-label="Search results">
            <h1>Search: “{query.trim()}”</h1>
            {hits.length === 0 && <p className="docs-muted">Nothing found. Try fewer or different words.</p>}
            <ul>
              {hits.map((h, i) => (
                <li key={`${h.guide.id}-${h.anchor}-${i}`}>
                  <a
                    href={docHref(h.guide.id, h.anchor)}
                    onClick={(e) => { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); navigate(h.guide.id === guide.id ? null : h.guide.id, h.anchor) }}
                  >
                    <span className="docs-hit-title">{h.heading}</span>
                    <span className="docs-hit-guide">{h.guide.title}</span>
                  </a>
                  <p>{h.snippet}</p>
                </li>
              ))}
            </ul>
          </section>
        ) : (
          <article>
            <DocMarkdown body={guide.body} onNavigate={navigate} />
          </article>
        )}
      </div>

      {!query && toc.length > 1 && (
        <aside className="docs-toc" aria-label="On this page">
          <div className="docs-toc-title">On this page</div>
          <ul>
            {toc.map((h) => (
              <li key={h.anchor}>
                <a href={`#${h.anchor}`} onClick={(e) => { e.preventDefault(); navigate(null, h.anchor) }}>
                  {h.text.replace(/`/g, '')}
                </a>
              </li>
            ))}
          </ul>
        </aside>
      )}
    </div>
  )
}
