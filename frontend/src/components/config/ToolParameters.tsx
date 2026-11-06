import { useState } from 'react'
import { API_BASE } from '../../types'
import { getToolSpec, useToolCatalogVersion } from '../../utils/toolCatalog'
import { describeParams } from '../../utils/toolParams'
import type { ParamSchema } from '../../utils/toolParams'

/** What the model sends a built-in tool, from its spec's parameter schema. */
export function ToolParametersInfo({ toolId }: { toolId: string }) {
  useToolCatalogVersion()  // re-render once the catalog has loaded
  const schema = getToolSpec(toolId)?.parameters
  if (!schema) return null
  const lines = describeParams(schema)
  return (
    <div className="form-group tool-params">
      <span className="field-label">The model calls it with</span>
      {lines.length ? (
        <ul className="tool-params-list">{lines.map((l) => <li key={l}><code>{l}</code></li>)}</ul>
      ) : <span className="field-hint">No arguments.</span>}
      <span className="field-hint">Arguments other than the main input override the same setting here for that call.</span>
    </div>
  )
}

export interface McpTool {
  name: string
  description?: string
  inputSchema?: ParamSchema
}

interface PickerProps {
  toolId: string
  config: Record<string, any>
  readOnly?: boolean
  onChange: (tools: McpTool[] | undefined) => void
}

/** An MCP server node's tools: discover them, then pick which the model may call (each as its own
 *  function with the server's input schema). None picked = the node takes one input string. */
export function McpToolsPicker({ toolId, config, readOnly, onChange }: PickerProps) {
  const stored: McpTool[] | undefined = config.mcp_tools
  const [found, setFound] = useState<McpTool[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const discover = async () => {
    setBusy(true)
    setError('')
    try {
      const { mcp_tools: _stored, ...rest } = config
      const res = await fetch(`${API_BASE}/api/tools/discover`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_type: toolId, config: rest }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${res.status}`)
      setFound(body.tools)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const listed = found ?? stored ?? []
  const picked = new Set((stored ?? []).map((t) => t.name))
  const toggle = (tool: McpTool) => {
    const next = picked.has(tool.name) ? (stored ?? []).filter((t) => t.name !== tool.name) : [...(stored ?? []), tool]
    onChange(next.length ? next : undefined)
  }

  return (
    <div className="form-group mcp-tools">
      <span className="field-label">Tools offered to the model</span>
      <span className="field-hint">
        {stored?.length
          ? `${stored.length} tool${stored.length === 1 ? '' : 's'}, each called with its own arguments.`
          : 'None picked: the model sends one input string, and the tool set in the config (tool_name) is called.'}
      </span>
      {!readOnly && (
        <button type="button" className="edit-code-btn" onClick={discover} disabled={busy}>
          {busy ? 'Starting the server…' : found ? '↻ Discover again' : '🔍 Discover tools'}
        </button>
      )}
      {error && <div className="field-error" role="alert">{error}</div>}
      {listed.length > 0 && (
        <ul className="mcp-tools-list">
          {listed.map((t) => (
            <li key={t.name}>
              <label>
                <input type="checkbox" checked={picked.has(t.name)} disabled={readOnly} onChange={() => toggle(t)} />
                {' '}<code>{t.name}</code>
                {t.description && <span className="field-hint"> — {t.description}</span>}
              </label>
              {picked.has(t.name) && describeParams(t.inputSchema).length > 0 && (
                <ul className="tool-params-list">
                  {describeParams(t.inputSchema).map((l) => <li key={l}><code>{l}</code></li>)}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
