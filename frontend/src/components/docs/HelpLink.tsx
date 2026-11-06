/**
 * A small "?" next to a setting that opens the user guide at the section explaining it. A plain
 * click switches to Docs in place (App listens for OPEN_DOCS_EVENT); Cmd/Ctrl-click opens a new tab.
 */
import { docHref, openDocs } from '../../utils/docLinks'
import '../../styles/docs.css'

export function HelpLink({ page, section = '', label = 'How this works' }: { page: string; section?: string; label?: string }) {
  return (
    <a
      className="help-link"
      href={docHref(page, section)}
      title={label}
      aria-label={label}
      onClick={(e) => {
        e.stopPropagation()
        if (e.metaKey || e.ctrlKey || e.shiftKey) return
        e.preventDefault()
        openDocs(page, section)
      }}
    >?</a>
  )
}
