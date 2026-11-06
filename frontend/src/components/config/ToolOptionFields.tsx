import { getToolSpec, useToolCatalogVersion } from '../../utils/toolCatalog'

interface Props {
  toolId: string
  config: Record<string, any>
  readOnly?: boolean
  onChange: (patch: Record<string, any>) => void
}

/** Dropdowns for a built-in tool's fixed-choice settings (language, engine, units, …), from its spec. */
export function ToolOptionFields({ toolId, config, readOnly, onChange }: Props) {
  useToolCatalogVersion()  // re-render once the catalog has loaded
  const selects = getToolSpec(toolId)?.config_options
  if (!selects) return null

  return (
    <>
      {Object.entries(selects).map(([key, field]) => {
        const value = String(config[key] ?? field.options[0].value)
        const known = field.options.some((o) => o.value === value)
        return (
          <div key={key} className="form-group">
            <label className="field-label">{field.label}</label>
            <select className="field-input" value={value} disabled={readOnly}
              onChange={(e) => onChange({ [key]: e.target.value })}>
              {/* keep a value set by hand in the JSON selectable */}
              {!known && <option value={value}>{value}</option>}
              {field.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {field.hint && <span className="field-hint">{field.hint}</span>}
          </div>
        )
      })}
    </>
  )
}
