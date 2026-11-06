import { NodeIcon } from './NodeIcon'
import { usePublishedApps } from '../utils/publishedApps'

interface Props {
  isOpen: boolean
  setIsOpen: (v: boolean) => void
}

/** Sidebar section: a single "Call Pipeline" node. The published pipeline is chosen in the node's config panel;
 * the count is how many are published. */
export function PipelinesSection({ isOpen, setIsOpen }: Props) {
  const { apps: published } = usePublishedApps()
  return (
    <>
      <div className="section-title-row collapsible mt-section" onClick={() => setIsOpen(!isOpen)}>
        <div className="section-title-left">
          <span className="section-chevron">{isOpen ? '▼' : '▶'}</span>
          <span className="section-heading"><NodeIcon kind="pipeline" />Pipelines</span>
        </div>
        <div className="section-title-right">
          <span className="section-subcount" title="Published pipelines you can call">{published.length}</span>
        </div>
      </div>
      {isOpen && (
        <div className="section-body">
          <div className="tool-icon-grid">
            <div
              className="tool-icon-chip"
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('application/univ-type', 'child_agent')
                e.dataTransfer.setData('application/univ-agent-role', 'Pipeline')
                e.dataTransfer.setData('application/univ-agent-kind', 'pipeline')
                e.dataTransfer.effectAllowed = 'move'
              }}
              title="Call Pipeline\nDrag onto the canvas, wire it to a Master Agent, then pick a published pipeline in its settings."
            >
              <span className="tool-icon-emoji">🔗</span>
              <span className="tool-icon-label">Call Pipeline</span>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
