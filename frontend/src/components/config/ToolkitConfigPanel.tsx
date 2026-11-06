import { useState } from 'react'
import type { ToolkitNodeData, FlowNode, ToolCatalogItem, ToolCategory } from '../../types'
import type { CustomToolRecord } from '../CustomToolModal'
import { HelpLink } from '../docs/HelpLink'

interface Props {
  activeNode: FlowNode
  toolCategories: ToolCategory[]
  customTools: CustomToolRecord[]
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function ToolkitConfigPanel({
  activeNode,
  toolCategories,
  customTools,
  onUpdate,
  onDelete,
  onSave,
  readOnly,
}: Props) {
  const [selectedToolId, setSelectedToolId] = useState<string>('')
  const data = activeNode.data as ToolkitNodeData
  const subTools = data.subTools || []

  const removeSubTool = (toolId: string) => {
    onUpdate(activeNode.id, {
      subTools: subTools.filter((t) => t.toolId !== toolId),
    })
  }

  // Get all standard tools
  const standardTools = toolCategories.flatMap((c) => c.tools)

  // Map custom tools to ToolCatalogItem format
  const customToolItems: ToolCatalogItem[] = customTools.map((ct) => ({
    id: `custom_${ct.id}`,
    name: ct.name,
    type: 'tool' as const,
    icon: ct.icon,
    description: ct.description,
    default_config: Object.fromEntries(ct.config_keys.map((k) => [k, ''])),
  }))

  const allAvailableTools = [...standardTools, ...customToolItems]

  // Filter out those already in the toolkit
  const remainingTools = allAvailableTools.filter(
    (t) => !subTools.some((st) => st.toolId === t.id)
  )

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity */}
      <div className="config-card">
        <h4 className="card-heading">1. Toolkit Identity<HelpLink page="03-tools" section="toolkits" label="About toolkits" /></h4>
        <div className="form-group">
          <label className="field-label">Toolkit Label</label>
          <input
            type="text"
            className="field-input"
            value={data.label}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Description</label>
          <textarea
            rows={2}
            className="field-textarea"
            value={data.description}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { description: e.target.value })}
          />
        </div>
      </div>

      {/* Card 2 — Sub-tools */}
      <div className="config-card">
        <h4 className="card-heading">2. Sub-tools ({subTools.length})</h4>
        {subTools.length === 0 ? (
          <p className="toolkit-panel-empty">
            No tools added yet. Drag any tool card from the sidebar and drop it directly onto this Toolkit node on the canvas.
          </p>
        ) : (
          <div className="toolkit-panel-subtool-list">
            {subTools.map((st) => (
              <div key={st.toolId} className="toolkit-panel-subtool-row">
                <span className="toolkit-panel-subtool-icon">{st.icon}</span>
                <div className="toolkit-panel-subtool-info">
                  <span className="toolkit-panel-subtool-name">{st.label}</span>
                  <span className="toolkit-panel-subtool-desc">{st.description}</span>
                </div>
                {!readOnly && (
                  <button
                    type="button"
                    className="toolkit-panel-remove-btn"
                    title="Remove sub-tool"
                    onClick={() => removeSubTool(st.toolId)}
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {!readOnly && (
          <p className="toolkit-add-hint" style={{ marginBottom: 8 }}>
            💡 Drop tool cards from the sidebar onto the Toolkit node to add sub-tools, or use the menu below:
          </p>
        )}

        {!readOnly && remainingTools.length > 0 && (
          <div className="toolkit-add-tool-row" style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <select
              className="field-input"
              style={{ flex: 1, height: 32, padding: '0 8px', fontSize: 12 }}
              value={selectedToolId}
              onChange={(e) => setSelectedToolId(e.target.value)}
            >
              <option value="">-- Choose a tool to add --</option>
              {remainingTools.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.icon || '🛠️'} {t.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="save-btn"
              style={{ height: 32, whiteSpace: 'nowrap', padding: '0 12px', fontSize: 12 }}
              disabled={!selectedToolId}
              onClick={() => {
                const toolToAdd = remainingTools.find((t) => t.id === selectedToolId)
                if (!toolToAdd) return
                onUpdate(activeNode.id, {
                  subTools: [
                    ...subTools,
                    {
                      toolId: toolToAdd.id,
                      toolType: toolToAdd.type,
                      label: toolToAdd.name,
                      icon: toolToAdd.icon || '🛠️',
                      description: toolToAdd.description,
                      config: { ...toolToAdd.default_config },
                    },
                  ],
                })
                setSelectedToolId('')
              }}
            >
              + Add Tool
            </button>
          </div>
        )}
      </div>

      {/* Card 3 — How the agent sees it */}
      <div className="config-card">
        <h4 className="card-heading">3. Agent Exposure</h4>
        <p className="toolkit-panel-empty" style={{ marginBottom: 8 }}>
          When connected to an LLM, the agent sees <strong>{subTools.length}</strong> individual tool function{subTools.length !== 1 ? 's' : ''} from this toolkit:
        </p>
        {subTools.length > 0 && (
          <div className="toolkit-fn-list">
            {subTools.map((st) => (
              <code key={st.toolId} className="toolkit-fn-chip">{st.toolId.replace(/-/g, '_')}</code>
            ))}
          </div>
        )}
      </div>

      {/* Card 4 — Actions */}
      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <div className="tool-status-box">
          <span className="status-dot online" />
          <span>Toolkit Active — {subTools.length} sub-tool{subTools.length !== 1 ? 's' : ''} available</span>
        </div>
        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>
    </div>
  )
}
