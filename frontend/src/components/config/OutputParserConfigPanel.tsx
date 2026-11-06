import type { OutputParserNodeData, FlowNode } from '../../types'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

const PARSER_HINTS: Record<OutputParserNodeData['parser_type'], string> = {
  json:     'Expects the LLM to return a valid JSON object. Retries automatically on parse failure.',
  pydantic: 'Validates and coerces the LLM output into a typed Pydantic schema. Requires a JSON schema.',
  regex:    'Extracts values from the output using named capture groups in a regular expression.',
  csv:      'Parses comma-separated output rows into a list of string arrays.',
  datetime: 'Parses natural language dates (e.g. "next Friday") into ISO-8601 datetime strings.',
  enum:     'Forces the output to exactly one of a predefined set of allowed string values.',
}

export function OutputParserConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as OutputParserNodeData

  return (
    <div className="bottom-config-grid">
      {/* Card 1 — Identity & Parser Type */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Parser Type</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Parser Type</label>
          <select className="field-select" value={data.parser_type} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { parser_type: e.target.value as OutputParserNodeData['parser_type'] })}>
            <option value="json">JSON — Parse output as a JSON object</option>
            <option value="pydantic">Pydantic — Validate against a typed schema</option>
            <option value="regex">Regex — Extract via named capture groups</option>
            <option value="csv">CSV — Parse comma-separated rows</option>
            <option value="datetime">DateTime — Natural language → ISO-8601</option>
            <option value="enum">Enum — Force one of a fixed set of values</option>
          </select>
          <span className="field-hint">{PARSER_HINTS[data.parser_type]}</span>
        </div>
      </div>

      {/* Card 2 — Schema / Pattern */}
      <div className="config-card">
        <h4 className="card-heading">2. Schema / Pattern</h4>
        {(data.parser_type === 'json' || data.parser_type === 'pydantic') && (
          <div className="form-group">
            <label className="field-label">JSON Schema</label>
            <textarea rows={5} className="field-textarea code-font"
              placeholder={'{\n  "name": {"type": "string"},\n  "score": {"type": "number"}\n}'}
              value={data.schema_json} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { schema_json: e.target.value })} />
            <span className="field-hint">JSON Schema definition the LLM output must conform to.</span>
          </div>
        )}
        {data.parser_type === 'regex' && (
          <div className="form-group">
            <label className="field-label">Regex Pattern</label>
            <input type="text" className="field-input code-font" placeholder="(?P<name>\w+)\s+(?P<score>\d+)"
              value={data.schema_json} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { schema_json: e.target.value })} />
            <span className="field-hint">Use named capture groups (?P&lt;name&gt;…) to extract structured fields.</span>
          </div>
        )}
        {data.parser_type === 'enum' && (
          <div className="form-group">
            <label className="field-label">Allowed Values (one per line)</label>
            <textarea rows={4} className="field-textarea code-font" placeholder={"positive\nnegative\nneutral"}
              value={data.schema_json} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { schema_json: e.target.value })} />
          </div>
        )}
        {(data.parser_type === 'csv' || data.parser_type === 'datetime') && (
          <div className="tool-status-box ret-status-box">
            <span className="status-dot ret-dot" />
            <span>No schema required for {data.parser_type} parsing.</span>
          </div>
        )}
      </div>

      {/* Card 3 — Strict Mode & Actions */}
      <div className="config-card">
        <h4 className="card-heading">3. Options &amp; Actions</h4>
        <div className="form-group">
          <label className="field-label">
            <input type="checkbox" checked={data.strict} disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { strict: e.target.checked })}
              style={{ marginRight: 8 }} />
            Strict Mode
          </label>
          <span className="field-hint">When enabled, any parse failure raises an error instead of passing raw output through.</span>
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
