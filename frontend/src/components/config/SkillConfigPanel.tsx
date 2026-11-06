import { useEffect, useState } from 'react'
import type { FlowNode, SkillNodeData, SkillRecord } from '../../types'
import { API_BASE } from '../../types'
import { HelpLink } from '../docs/HelpLink'

type Library = { skill: SkillRecord; versions: { version: number; created_at: string }[] }

/**
 * A Skill node that names a library skill (skill_id) runs the library's copy, read when the run
 * starts (backend services/skills_runtime.py), so it's shown read-only here with a version picker:
 * "Latest" follows every edit, a pinned version stays as it was. Nodes without a library skill (old
 * graphs) keep editing their own copy.
 */
function LibrarySkill({ nodeId, data, lib, onUpdate, readOnly }: {
  nodeId: string; data: SkillNodeData; lib: Library
  onUpdate: (nodeId: string, fields: Record<string, any>) => void; readOnly?: boolean
}) {
  const { skill, versions } = lib
  return (
    <div className="bottom-config-grid">
      <div className="config-card">
        <h4 className="card-heading">{skill.icon} {skill.name}<HelpLink page="05-agents-workflows-skills" section="skills" label="How skills load" /></h4>
        <div className="form-group">
          <label className="field-label" htmlFor={`skill-version-${nodeId}`}>Version</label>
          <select id={`skill-version-${nodeId}`} className="field-select" disabled={readOnly || skill.builtin}
            value={data.skill_version ?? ''}
            onChange={(e) => onUpdate(nodeId, { skill_version: e.target.value ? Number(e.target.value) : undefined })}>
            <option value="">Latest (v{skill.version ?? 1}) — follows every edit</option>
            {versions.map((v) => (
              <option key={v.version} value={v.version}>Pin v{v.version} · {new Date(v.created_at).toLocaleDateString()}</option>
            ))}
          </select>
        </div>
        <div className="form-group">
          <span className="field-label">When to use</span>
          <p className="field-hint" style={{ margin: 0 }}>{skill.when_to_use || skill.description || '—'}</p>
        </div>
        <div className="form-group">
          <span className="field-label">Tools it needs</span>
          <p className="field-hint" style={{ margin: 0 }}>
            {(skill.required_tools ?? skill.tool_ids ?? []).join(', ') || 'None'} — attach them to the LLM node;
            they stay hidden until the model loads this skill.
          </p>
          {skill.builtin && skill.available === false && (
            <p className="field-hint" style={{ margin: 0, color: '#b45309' }}>Install its tools in Settings → Tools &amp; MCP packages.</p>
          )}
        </div>
      </div>
      <div className="config-card" style={{ gridColumn: 'span 2' }}>
        <h4 className="card-heading">Instructions (returned when the model loads it)</h4>
        <pre className="field-textarea" style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 11, margin: 0, maxHeight: 220, overflow: 'auto' }}>
          {skill.instructions || '—'}
        </pre>
        <span className="field-hint">
          {skill.builtin ? 'A built-in skill: copy it in the Skills library to change it.'
            : 'Edit it in the Skills library (sidebar → Agent Skills → ✎). Every pipeline on “Latest” gets the change.'}
        </span>
      </div>
    </div>
  )
}

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function SkillConfigPanel({ activeNode, onUpdate, onDelete: _onDelete, onSave: _onSave, readOnly }: Props) {
  const data = activeNode.data as SkillNodeData
  const [lib, setLib] = useState<Library | null | 'missing'>(null)

  useEffect(() => {
    if (!data.skill_id) return
    let live = true
    const id = encodeURIComponent(data.skill_id)
    Promise.all([fetch(`${API_BASE}/api/skills/${id}`), fetch(`${API_BASE}/api/skills/${id}/versions`)])
      .then(async ([s, v]) => {
        if (!live) return
        setLib(s.ok ? { skill: await s.json(), versions: v.ok ? await v.json() : [] } : 'missing')
      })
      .catch(() => { if (live) setLib('missing') })
    return () => { live = false }
  }, [data.skill_id])

  if (data.skill_id && lib && lib !== 'missing') {
    return <LibrarySkill nodeId={activeNode.id} data={data} lib={lib} onUpdate={onUpdate} readOnly={readOnly} />
  }

  return (
    <div className="bottom-config-grid">
      {/* ── Card 1: Identity & Categorisation ─────────────────────────────── */}
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Category<HelpLink page="05-agents-workflows-skills" section="skills" label="Writing good skills" /></h4>
        <div className="form-group">
          <label className="field-label">Skill Name</label>
          <input
            type="text"
            className="field-input"
            value={data.label || ''}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })}
            placeholder="e.g. Deep Research & Synthesis"
          />
        </div>
        <div className="form-row">
          <div className="form-group" style={{ width: 70 }}>
            <label className="field-label">Icon</label>
            <input
              type="text"
              className="field-input"
              value={data.icon || '⚡'}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { icon: e.target.value })}
            />
          </div>
          <div className="form-group flex-1">
            <label className="field-label">Category</label>
            <select
              className="field-select"
              value={data.category || 'general'}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { category: e.target.value })}
            >
              <option value="general">General</option>
              <option value="analysis">Research &amp; Analysis</option>
              <option value="engineering">Engineering &amp; Code</option>
              <option value="operations">Operations &amp; DevOps</option>
            </select>
          </div>
        </div>
        <div className="form-group">
          <label className="field-label">Tags (comma-separated)</label>
          <input
            type="text"
            className="field-input"
            value={(data.tags || []).join(', ')}
            disabled={readOnly}
            onChange={(e) =>
              onUpdate(activeNode.id, {
                tags: e.target.value
                  .split(',')
                  .map((t) => t.trim())
                  .filter(Boolean),
              })
            }
            placeholder="research, fact-checking, synthesis"
          />
        </div>
      </div>

      {/* ── Card 2: Activation Trigger Criteria ───────────────────────────── */}
      <div className="config-card">
        <h4 className="card-heading">2. When to use</h4>
        {data.skill_id && lib === 'missing' && (
          <p className="field-hint" style={{ margin: '0 0 6px', color: '#b45309' }}>
            This skill isn't in the project's library any more, so runs use the copy on this node.
          </p>
        )}
        <div className="form-group flex-1">
          <label className="field-label">When the user asks to… ({(data.description || '').length} / 300)</label>
          <textarea
            className="field-textarea"
            rows={5}
            style={{ width: '100%', height: 'calc(100% - 24px)', minHeight: 90, boxSizing: 'border-box' }}
            value={data.description || ''}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { description: e.target.value })}
            placeholder="Explain when and why an agent should activate this skill..."
          />
          <span className="field-hint">All the model sees until it loads the skill (on-demand mode).</span>
        </div>
      </div>

      {/* ── Card 3: Instructions & SOP ────────────────────────────────────── */}
      <div className="config-card" style={{ gridColumn: 'span 2' }}>
        <h4 className="card-heading">3. Standard Operating Procedures (SOP) &amp; Prompt Rules</h4>
        <div className="form-group flex-1">
          <label className="field-label">Injected System Instructions</label>
          <textarea
            className="field-textarea"
            rows={5}
            style={{ width: '100%', height: 'calc(100% - 24px)', minHeight: 90, boxSizing: 'border-box', fontFamily: 'monospace', fontSize: 11 }}
            value={data.instructions || ''}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { instructions: e.target.value })}
            placeholder="Step-by-step instructions, heuristics, or prompt rules to inject into the agent runtime..."
          />
          <span className="field-hint">Returned to the model when it loads the skill; in “Always in the prompt” mode (and for Child agents) added to the system prompt.</span>
        </div>
      </div>
    </div>
  )
}
