/**
 * A ```mermaid block in the docs (docs/architecture uses them, and GitHub draws them too). Mermaid is
 * large, so it's loaded only when a page has a diagram. Until it has drawn, or if it can't, the
 * diagram's source is shown as a code block.
 */
import { useEffect, useId, useState } from 'react'

type MermaidApi = typeof import('mermaid').default

let loading: Promise<MermaidApi> | null = null

function loadMermaid(): Promise<MermaidApi> {
  loading ??= import('mermaid').then(({ default: mermaid }) => {
    // strict: labels are sanitized and click handlers are disabled
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral', fontFamily: 'inherit' })
    return mermaid
  })
  return loading
}

export function DocDiagram({ source }: { source: string }) {
  const id = `doc-diagram-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const [svg, setSvg] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    loadMermaid()
      .then((mermaid) => mermaid.render(id, source))
      .then(({ svg: drawn }) => { if (!cancelled) setSvg(drawn) })
      .catch(() => { if (!cancelled) setSvg(null) })
    return () => { cancelled = true }
  }, [id, source])

  if (!svg) return <pre className="doc-code" data-lang="mermaid"><code>{source}</code></pre>
  // The SVG comes from mermaid's strict mode (sanitized) and the source from our own bundled docs
  return <div className="doc-diagram" role="img" aria-label="Diagram" dangerouslySetInnerHTML={{ __html: svg }} />
}
