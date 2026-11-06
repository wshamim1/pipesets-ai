import { useState } from 'react'
import type { Node } from '@xyflow/react'
import { API_BASE } from '../../types'
import type { KnowledgeBaseNodeData } from '../../types'

interface Props {
  activeNode: Node<KnowledgeBaseNodeData, 'knowledge_base'>
  onUpdate: (id: string, partial: Partial<KnowledgeBaseNodeData>) => void
  onDelete: (id: string) => void
  onSave: () => void
  readOnly?: boolean
}

export function KnowledgeBaseConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data

  // Test search query
  const [testQuery, setTestQuery] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [searchResults, setSearchResults] = useState<any[] | null>(null)

  const handleTestSearch = async () => {
    if (!testQuery.trim()) return
    setIsSearching(true)
    setSearchResults(null)
    try {
      const res = await fetch(`${API_BASE}/api/knowledge-bases/${data.kb_id}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: testQuery, top_k: data.top_k || 3, score_threshold: data.score_threshold || 0 }),
      })
      if (res.ok) {
        const d = await res.json()
        setSearchResults(d.results || [])
      }
    } catch {
      /* ignore search errors */
    } finally {
      setIsSearching(false)
    }
  }

  return (
    <div className="bottom-config-grid">
      {/* 1. Details */}
      <div className="config-card">
        <h4 className="card-heading">1. Knowledge Base Info</h4>
        <div className="form-group">
          <label className="field-label">Label</label>
          <input
            type="text"
            className="field-input"
            value={data.label}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Indexed Chunks</label>
          <input
            type="text"
            className="field-input"
            value={`${data.chunk_count || 0} chunks (${data.embedding_provider === 'openai' ? 'OpenAI' : 'Local MiniLM'})`}
            disabled
            style={{ background: '#f8fafc', color: '#64748b' }}
          />
        </div>
      </div>

      {/* 2. Retrieval Parameters */}
      <div className="config-card">
        <h4 className="card-heading">2. Search Settings</h4>
        <div className="form-group">
          <label className="field-label">Top-K Passages: {data.top_k || 4}</label>
          <input
            type="range"
            min={1}
            max={10}
            className="field-slider"
            value={data.top_k || 4}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { top_k: Number(e.target.value) })}
          />
        </div>
        <div className="form-group">
          <label className="field-label">Score Threshold: {data.score_threshold || 0}</label>
          <input
            type="range"
            min={0}
            max={0.9}
            step={0.05}
            className="field-slider"
            value={data.score_threshold || 0}
            disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { score_threshold: Number(e.target.value) })}
          />
        </div>
      </div>

      {/* 3. Live Test Search */}
      <div className="config-card">
        <h4 className="card-heading">3. Test Semantic Query</h4>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            type="text"
            className="field-input text-xs"
            placeholder="Ask question over this KB..."
            value={testQuery}
            disabled={readOnly}
            onChange={(e) => setTestQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !readOnly && handleTestSearch()}
          />
          <button
            type="button"
            className="mcp-test-btn"
            style={{ padding: '4px 8px', fontSize: 11 }}
            onClick={handleTestSearch}
            disabled={isSearching}
          >
            {isSearching ? '...' : 'Search'}
          </button>
        </div>
        {searchResults && (
          <div style={{ marginTop: 6, maxHeight: 75, overflowY: 'auto', fontSize: 10, color: '#334155' }}>
            {searchResults.length === 0 ? (
              <span className="field-hint">No matches found.</span>
            ) : (
              searchResults.map((r, i) => (
                <div key={i} style={{ borderBottom: '1px solid #e2e8f0', padding: '2px 0' }}>
                  <strong>[Score {(r.score || 0).toFixed(2)}]</strong> {r.content.slice(0, 80)}...
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* 4. Actions */}
      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
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
