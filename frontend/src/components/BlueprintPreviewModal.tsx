import { useEffect, useMemo, useState } from 'react'
import type { Node } from '@xyflow/react'
import { ReadOnlyFlow } from './ReadOnlyFlow'
import { useCredentials } from '../context/CredentialsContext'
import { validatePipeline } from '../utils/pipelineValidation'
import { useRequiredConfig } from '../utils/toolCatalog'
import { buildBlueprintFlow } from '../blueprints'
import type { StarterBlueprint } from '../blueprints'

interface Props {
  blueprint: StarterBlueprint
  onClose: () => void
  onClone: (blueprint: StarterBlueprint) => Promise<void>
}

// Config fields that are credentials or targets the user must supply after cloning.
// A bare tool `api_key` is optional (Weather → Open-Meteo, Web Search → DuckDuckGo), so it is not flagged.
const SETUP_FIELD = /(?<!^api)_key$|token|secret|password|webhook|connection_string|username|address|_url$/i

function pendingSetup(nodes: Node[]): string[] {
  const out: string[] = []
  for (const n of nodes) {
    const d = n.data as Record<string, any>
    const missing = new Set<string>()
    const scan = (obj: Record<string, any> | undefined) => {
      for (const [k, v] of Object.entries(obj ?? {})) {
        if (v === '' && SETUP_FIELD.test(k)) missing.add(k)
      }
    }
    if (n.type === 'tool') {
      scan(d.config)
      scan(d.config?.env_vars)
    }
    if (n.type === 'doc_loader' && String(d.source ?? '').startsWith('/path/to/')) missing.add('source')
    if (missing.size) out.push(`${d.label}: ${[...missing].join(', ')}`)
  }
  return out
}

/** Read-only look at a starter blueprint's flow before it is cloned into a new app. */
export function BlueprintPreviewModal({ blueprint, onClose, onClone }: Props) {
  const { resolveApiKey } = useCredentials()
  const requiredConfig = useRequiredConfig()
  const [cloning, setCloning] = useState(false)
  const flow = useMemo(() => buildBlueprintFlow(blueprint.id), [blueprint.id])
  const nodes = flow.nodes as Node[]

  const keyIssues = useMemo(
    () => validatePipeline(flow.nodes, flow.edges, resolveApiKey, requiredConfig).filter((i) => i.severity === 'error'),
    [flow, resolveApiKey, requiredConfig],
  )
  const setup = useMemo(() => pendingSetup(nodes), [nodes])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const clone = async () => {
    setCloning(true)
    try {
      await onClone(blueprint)
    } finally {
      setCloning(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card pipeline-preview-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="pipeline-preview-title">
            <div className="pipeline-preview-crumbs">
              <span style={{ marginRight: 6 }}>{blueprint.icon}</span>
              <strong>{blueprint.name}</strong>
              <span className="blueprint-preview-badge">{blueprint.badge}</span>
            </div>
            <span className="field-hint">
              {nodes.length} nodes · {flow.edges.length} edges · preview · {blueprint.description}
            </span>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose}>✕</button>
        </div>
        <div className="pipeline-preview-body">
          <ReadOnlyFlow nodes={nodes} edges={flow.edges} />
        </div>
        <div className="modal-actions blueprint-preview-footer">
          <div className="blueprint-preview-setup">
            {keyIssues.length === 0 && setup.length === 0 ? (
              <span>✓ Ready to run after cloning.</span>
            ) : (
              <>
                <strong>Set up after cloning:</strong>{' '}
                {[...new Set(keyIssues.map((i) => i.title)), ...setup].join(' · ')}
              </>
            )}
          </div>
          <button type="button" className="modal-cancel-btn" onClick={onClose}>Close</button>
          <button type="button" className="modal-create-btn" onClick={clone} disabled={cloning}>
            {cloning ? 'Cloning…' : '+ Clone Blueprint'}
          </button>
        </div>
      </div>
    </div>
  )
}
