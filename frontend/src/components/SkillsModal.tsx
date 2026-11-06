import { useState } from 'react'
import type { SkillRecord } from '../types'
import { API_BASE } from '../types'
import { useTenantContext } from '../context/TenantContext'

interface Props {
  skills: SkillRecord[]
  isOpen: boolean
  onClose: () => void
  onSave: () => void
  onDeleteSkill: (skill: SkillRecord) => void
}

export function SkillsModal({ skills, isOpen, onClose, onSave, onDeleteSkill }: Props) {
  const { scope } = useTenantContext()
  const tenantId = scope.tenantId
  const projectId = scope.projectId
  const [editingSkill, setEditingSkill] = useState<Partial<SkillRecord> | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  if (!isOpen) return null

  const handleOpenCreate = () => {
    setEditingSkill({
      name: '',
      icon: '⚡',
      category: 'general',
      description: '',
      instructions: '',
      tags: [],
      tool_ids: [],
    })
    setErrorMsg('')
  }

  const handleEdit = (skill: SkillRecord) => {
    setEditingSkill({ ...skill })
    setErrorMsg('')
  }

  const handleSave = async () => {
    if (!editingSkill?.name?.trim()) {
      setErrorMsg('Skill name is required.')
      return
    }

    setIsSubmitting(true)
    setErrorMsg('')

    try {
      const isUpdate = Boolean(editingSkill.id && !editingSkill.builtin)
      const url = isUpdate ? `${API_BASE}/api/skills/${editingSkill.id}` : `${API_BASE}/api/skills`
      const method = isUpdate ? 'PUT' : 'POST'

      const res = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-Id': tenantId,
          'X-Project-Id': projectId,
        },
        body: JSON.stringify({
          name: editingSkill.name,
          icon: editingSkill.icon || '⚡',
          category: editingSkill.category || 'general',
          description: editingSkill.description || '',
          instructions: editingSkill.instructions || '',
          tags: editingSkill.tags || [],
          tool_ids: editingSkill.tool_ids || [],
        }),
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to save skill')
      }

      setEditingSkill(null)
      onSave()
    } catch (err: any) {
      setErrorMsg(err.message || 'Error saving skill')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-container skill-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '800px', width: '90%' }}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '20px', fontFamily: '"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif' }}>⚡</span>
            <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>Agent Skills Catalog</h2>
          </div>
          <button className="modal-close-btn" onClick={onClose}>×</button>
        </div>

        <div className="modal-body" style={{ maxHeight: '75vh', overflowY: 'auto', padding: '16px' }}>
          {editingSkill ? (
            <div className="skill-edit-form" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0, fontSize: '15px', color: '#e2e8f0' }}>
                  {editingSkill.id ? 'Edit Skill' : 'Create New Skill'}
                </h3>
                <button
                  className="btn btn-secondary"
                  style={{ padding: '4px 10px', fontSize: '12px' }}
                  onClick={() => setEditingSkill(null)}
                >
                  Cancel
                </button>
              </div>

              {errorMsg && (
                <div style={{ background: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', color: '#fca5a5', padding: '8px 12px', borderRadius: '6px', fontSize: '13px' }}>
                  {errorMsg}
                </div>
              )}

              <div style={{ display: 'flex', gap: '12px' }}>
                <div style={{ width: '80px' }}>
                  <label className="config-label">Icon</label>
                  <input
                    type="text"
                    className="config-input"
                    value={editingSkill.icon || ''}
                    onChange={(e) => setEditingSkill({ ...editingSkill, icon: e.target.value })}
                    placeholder="⚡"
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <label className="config-label">Skill Name *</label>
                  <input
                    type="text"
                    className="config-input"
                    value={editingSkill.name || ''}
                    onChange={(e) => setEditingSkill({ ...editingSkill, name: e.target.value })}
                    placeholder="e.g. Statistical Analysis"
                  />
                </div>
                <div style={{ width: '160px' }}>
                  <label className="config-label">Category</label>
                  <select
                    className="config-select"
                    value={editingSkill.category || 'general'}
                    onChange={(e) => setEditingSkill({ ...editingSkill, category: e.target.value })}
                  >
                    <option value="general">General</option>
                    <option value="analysis">Analysis</option>
                    <option value="engineering">Engineering</option>
                    <option value="research">Research</option>
                    <option value="operations">Operations</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="config-label">
                  When to use <span style={{ color: (editingSkill.description || '').length > 300 ? '#f87171' : '#94a3b8', fontWeight: 400 }}>
                    {(editingSkill.description || '').length} / 300</span>
                </label>
                <textarea
                  className="config-textarea"
                  rows={2}
                  value={editingSkill.description || ''}
                  onChange={(e) => setEditingSkill({ ...editingSkill, description: e.target.value })}
                  placeholder="When the user asks to… (e.g. When the user asks why an Airflow DAG run failed)"
                />
                <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                  All the agent sees until it loads the skill. Write it as “When the user asks to…”.
                </span>
              </div>

              <div>
                <label className="config-label">Standard Operating Procedures & Instructions *</label>
                <textarea
                  className="config-textarea"
                  rows={6}
                  value={editingSkill.instructions || ''}
                  onChange={(e) => setEditingSkill({ ...editingSkill, instructions: e.target.value })}
                  placeholder="Step-by-step instructions, heuristics, or prompt rules to inject..."
                />
              </div>

              <div>
                <label className="config-label">Tools it needs (tool ids, comma-separated)</label>
                <input
                  type="text"
                  className="config-input"
                  value={(editingSkill.tool_ids || []).join(', ')}
                  onChange={(e) =>
                    setEditingSkill({
                      ...editingSkill,
                      tool_ids: e.target.value.split(',').map((t) => t.trim()).filter(Boolean),
                    })
                  }
                  placeholder="airflow, airflow_task_logs"
                />
                <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                  Attached to the agent, these stay hidden until it loads this skill.
                </span>
              </div>

              <div>
                <label className="config-label">Tags (comma-separated)</label>
                <input
                  type="text"
                  className="config-input"
                  value={(editingSkill.tags || []).join(', ')}
                  onChange={(e) =>
                    setEditingSkill({
                      ...editingSkill,
                      tags: e.target.value.split(',').map((t) => t.trim()).filter(Boolean),
                    })
                  }
                  placeholder="data, stats, python"
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '12px' }}>
                <button className="btn btn-secondary" onClick={() => setEditingSkill(null)}>
                  Cancel
                </button>
                <button className="btn btn-primary" onClick={handleSave} disabled={isSubmitting}>
                  {isSubmitting ? 'Saving...' : 'Save Skill'}
                </button>
              </div>
            </div>
          ) : (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                <div style={{ fontSize: '13px', color: '#94a3b8' }}>
                  Modular capability packages for Agents and LLM nodes.
                </div>
                <button className="btn btn-primary" onClick={handleOpenCreate} style={{ padding: '6px 14px', fontSize: '13px' }}>
                  + Create Skill
                </button>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '12px' }}>
                {skills.map((skill) => (
                  <div
                    key={skill.id}
                    style={{
                      background: 'rgba(30, 41, 59, 0.7)',
                      border: '1px solid rgba(148, 163, 184, 0.15)',
                      borderRadius: '8px',
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '20px', fontFamily: '"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif', lineHeight: 1 }}>{skill.icon || '⚡'}</span>
                        <div>
                          <div style={{ fontWeight: 600, color: '#f8fafc', fontSize: '14px' }}>{skill.name}</div>
                          <span style={{ fontSize: '11px', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                            {skill.category}{skill.version ? ` · v${skill.version}` : ''}
                          </span>
                        </div>
                      </div>

                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button
                          style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '14px' }}
                          onClick={() => handleEdit(skill)}
                          title="Edit"
                        >
                          ✎
                        </button>
                        {!skill.builtin && (
                          <button
                            style={{ background: 'none', border: 'none', color: '#f87171', cursor: 'pointer', fontSize: '14px' }}
                            onClick={() => onDeleteSkill(skill)}
                            title="Delete"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    </div>

                    <p style={{ margin: 0, fontSize: '12px', color: '#cbd5e1', lineHeight: '1.4' }}>
                      {skill.description || 'No description provided.'}
                    </p>
                    {(skill.tool_ids?.length ?? 0) > 0 && (
                      <p style={{ margin: 0, fontSize: '11px', color: '#94a3b8' }}>🔧 {skill.tool_ids.join(', ')}</p>
                    )}
                    {skill.builtin && skill.available === false && (
                      <p style={{ margin: 0, fontSize: '11px', color: '#fbbf24' }}>
                        Install its tools in Settings → Tools &amp; MCP packages to use it.
                      </p>
                    )}

                    {skill.tags && skill.tags.length > 0 && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: 'auto', paddingTop: '6px' }}>
                        {skill.tags.map((t, idx) => (
                          <span
                            key={idx}
                            style={{
                              fontSize: '10px',
                              background: 'rgba(234, 179, 8, 0.12)',
                              color: '#facc15',
                              padding: '2px 6px',
                              borderRadius: '4px',
                            }}
                          >
                            #{t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
