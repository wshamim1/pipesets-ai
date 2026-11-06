import { Handle, Position } from '@xyflow/react'
import type { NodeProps, Node } from '@xyflow/react'
import type { MiddlewareNodeData } from '../types'
import { NodeIcon } from '../components/NodeIcon'

export function MiddlewareNode({ data, selected }: NodeProps<Node<MiddlewareNodeData, 'middleware'>>) {
  const isCardSelected = selected || data.isSelected

  const TYPE_META: Record<string, { label: string; color: string }> = {
    content_moderation: { label: 'Content Moderation', color: '#7c3aed' },
    cost_tracker:       { label: 'Cost Tracker',       color: '#b45309' },
    rate_limiter:       { label: 'Rate Limiter',       color: '#0f766e' },
    prompt_injection:   { label: 'Prompt Injection',   color: '#be123c' },
    grounding:          { label: 'Grounding Check',    color: '#1d4ed8' },
    custom_rule:        { label: 'Custom Rule',        color: '#0e7490' },
    custom_pattern:     { label: 'Custom Pattern',     color: '#4d7c0f' },
  }
  const meta = TYPE_META[data.middleware_type] ?? { label: 'Guardrail', color: '#475569' }

  const summary = (() => {
    if (data.middleware_type === 'content_moderation') {
      const pii = data.config?.pii_detection !== false ? 'PII on' : 'PII off'
      const patterns = data.config?.blocked_patterns?.length ?? 3
      return `${patterns} patterns · ${pii}`
    }
    if (data.middleware_type === 'cost_tracker') {
      const budget = data.config?.max_cost_per_run ? `$${data.config.max_cost_per_run}/run` : 'no cap'
      const tokens = data.config?.max_tokens_per_run ? `${data.config.max_tokens_per_run.toLocaleString()} tok` : ''
      return [budget, tokens].filter(Boolean).join(' · ')
    }
    if (data.middleware_type === 'rate_limiter') {
      const rpm = data.config?.max_rpm ?? 20
      const window = data.config?.window_seconds ?? 60
      return `${rpm} req / ${window}s`
    }
    if (data.middleware_type === 'grounding') {
      const empty = { answer: 'empty → fixed reply', instruct: 'empty → warn model', off: 'empty → no action' }[
        (data.config?.on_empty_tools ?? 'answer') as 'answer' | 'instruct' | 'off']
      const facts = data.config?.check_facts === false ? 'fact check off' : `fact check · ${data.config?.action_on_fail ?? 'block'}`
      return `${empty} · ${facts}`
    }
    if (data.middleware_type === 'custom_rule') {
      const rules: string[] = [...(data.config?.rule ? [data.config.rule] : []), ...(data.config?.rules ?? [])]
      if (!rules.length) return 'no rules yet'
      const first = rules[0].length > 40 ? rules[0].slice(0, 40) + '…' : rules[0]
      return rules.length === 1 ? `“${first}”` : `“${first}” + ${rules.length - 1} more`
    }
    if (data.middleware_type === 'custom_pattern') {
      const n = (data.config?.patterns ?? []).filter(Boolean).length
      const where = { prompt: 'prompt', response: 'answer', both: 'prompt + answer' }[(data.config?.apply_to ?? 'both') as 'prompt' | 'response' | 'both']
      return `${n} ${data.config?.mode === 'regex' ? 'regex' : 'word'}${n === 1 ? '' : 's'} · ${where}`
    }
    return 'configured'
  })()

  return (
    <div className={`middleware-node-card ${isCardSelected ? 'selected' : ''}`}
      style={{ borderLeftColor: meta.color }}>
      <Handle type="target" position={Position.Left}   id="mw-target-left"   className="flow-handle mw-handle" />
      <Handle type="source" position={Position.Left}   id="mw-source-left"   className="flow-handle mw-handle" />
      <Handle type="target" position={Position.Top}    id="mw-target-top"    className="flow-handle mw-handle" />
      <Handle type="source" position={Position.Top}    id="mw-source-top"    className="flow-handle mw-handle" />

      <div className="node-card-header" style={{ background: `${meta.color}12`, borderBottom: `1px solid ${meta.color}30` }}>
        <div className="node-card-title-row">
          <span className="node-icon"><NodeIcon kind="middleware" variant={data.middleware_type} /></span>
          <span className="node-title">{data.label}</span>
        </div>
        <button type="button" className="node-delete-btn" title="Remove node"
          onClick={(e) => { e.stopPropagation(); data.onDelete?.() }}>✕</button>
      </div>

      <div className="node-card-body">
        <div className="node-badge-row">
          <span className="chip chip-middleware" style={{ background: `${meta.color}18`, color: meta.color, borderColor: `${meta.color}40` }}>
            GUARDRAIL
          </span>
          <span className="chip model-chip">{meta.label}</span>
        </div>
        <div className="node-meta-row">
          <span className="meta-item" style={{ color: '#475569', fontSize: 10 }}>{summary}</span>
        </div>
        {!data.enabled && (
          <div style={{ marginTop: 4, fontSize: 9, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase' }}>
            ⏸ disabled
          </div>
        )}
      </div>

      <div className="node-card-footer">
        <span className="footer-status" style={{ color: meta.color }}>
          {isCardSelected ? `● ${meta.label} active` : 'Guards connected LLM nodes'}
        </span>
      </div>

      <Handle type="target" position={Position.Right}  id="mw-target-right"  className="flow-handle mw-handle" />
      <Handle type="source" position={Position.Right}  id="mw-source-right"  className="flow-handle mw-handle" />
      <Handle type="target" position={Position.Bottom} id="mw-target-bottom" className="flow-handle mw-handle" />
      <Handle type="source" position={Position.Bottom} id="mw-source-bottom" className="flow-handle mw-handle" />
    </div>
  )
}
