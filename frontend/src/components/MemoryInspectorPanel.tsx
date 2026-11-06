import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../types'
import { KeyValueStorePanel } from './ops/KeyValueStorePanel'
import { LongTermMemoryPanel } from './ops/LongTermMemoryPanel'

interface SessionSummary {
  session_id: string
  message_count: number
  total_tokens: number
  last_updated: string
  first_prompt?: string
}

interface SessionMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  token_count: number
  created_at: string
}

interface Props {
  currentSessionId?: string
  onSelectSession?: (sessionId: string) => void
}

export function MemoryInspectorPanel(props: Props) {
  const [view, setView] = useState<'sessions' | 'long-term' | 'store'>('sessions')
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div className="ltm-switch" role="tablist" aria-label="Memory">
        <button type="button" role="tab" aria-selected={view === 'sessions'}
          className={`ltm-switch-btn${view === 'sessions' ? ' ltm-switch-btn--active' : ''}`}
          onClick={() => setView('sessions')}>Conversations</button>
        <button type="button" role="tab" aria-selected={view === 'long-term'}
          className={`ltm-switch-btn${view === 'long-term' ? ' ltm-switch-btn--active' : ''}`}
          onClick={() => setView('long-term')}>Long-term</button>
        <button type="button" role="tab" aria-selected={view === 'store'}
          className={`ltm-switch-btn${view === 'store' ? ' ltm-switch-btn--active' : ''}`}
          onClick={() => setView('store')}>Store</button>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        {view === 'sessions' ? <SessionsInspector {...props} /> : view === 'long-term' ? <LongTermMemoryPanel /> : <KeyValueStorePanel />}
      </div>
    </div>
  )
}

function SessionsInspector({ currentSessionId, onSelectSession }: Props) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string>(currentSessionId || '')
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/memory`)
      if (res.ok) {
        const data = await res.json()
        setSessions(data.sessions || [])
        if (!selectedSessionId && data.sessions?.length > 0) {
          setSelectedSessionId(data.sessions[0].session_id)
        }
      }
    } catch {
      setSessions([])
    }
  }, [selectedSessionId])

  const fetchSessionDetails = useCallback(async (sid: string) => {
    if (!sid) {
      setMessages([])
      return
    }
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/memory/${encodeURIComponent(sid)}?token_budget=50000`)
      if (res.ok) {
        const data = await res.json()
        setMessages(data.messages || [])
      } else {
        setMessages([])
      }
    } catch {
      setMessages([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  useEffect(() => {
    if (selectedSessionId) {
      fetchSessionDetails(selectedSessionId)
    }
  }, [selectedSessionId, fetchSessionDetails])

  const handleClearSession = async (sid: string) => {
    await fetch(`${API_BASE}/api/memory/${encodeURIComponent(sid)}`, { method: 'DELETE' })
    if (selectedSessionId === sid) {
      setMessages([])
    }
    fetchSessions()
  }

  const handleDeleteMessage = async (idx: number) => {
    if (!selectedSessionId) return
    await fetch(`${API_BASE}/api/memory/${encodeURIComponent(selectedSessionId)}/messages/${idx}`, {
      method: 'DELETE',
    })
    fetchSessionDetails(selectedSessionId)
    fetchSessions()
  }

  const filteredSessions = sessions.filter(
    (s) =>
      s.session_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (s.first_prompt && s.first_prompt.toLowerCase().includes(searchTerm.toLowerCase()))
  )

  const totalAllTokens = sessions.reduce((acc, s) => acc + (s.total_tokens || 0), 0)
  const totalAllMessages = sessions.reduce((acc, s) => acc + (s.message_count || 0), 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', fontSize: 13 }}>
      {/* Top Header stats */}
      <div style={{ padding: '10px 14px', borderBottom: '1px solid #e2e8f0', background: '#f8fafc', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontWeight: 600, color: '#1e293b' }}>🧠 Memory Inspector</span>
          <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
            {sessions.length} active sessions • {totalAllMessages} messages • ~{totalAllTokens.toLocaleString()} tokens
          </div>
        </div>
        <button
          type="button"
          onClick={fetchSessions}
          style={{ padding: '3px 8px', borderRadius: 4, border: '1px solid #cbd5e1', background: '#fff', fontSize: 11, cursor: 'pointer' }}
        >
          🔄 Refresh
        </button>
      </div>

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Left: Session List */}
        <div style={{ width: '42%', borderRight: '1px solid #e2e8f0', display: 'flex', flexDirection: 'column', background: '#ffffff' }}>
          <div style={{ padding: 6, borderBottom: '1px solid #f1f5f9' }}>
            <input
              type="text"
              placeholder="Search sessions..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              style={{ width: '100%', padding: '4px 8px', fontSize: 12, border: '1px solid #cbd5e1', borderRadius: 4, boxSizing: 'border-box' }}
            />
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filteredSessions.length === 0 ? (
              <div style={{ padding: 14, color: '#94a3b8', textAlign: 'center', fontSize: 12 }}>
                No memory sessions found
              </div>
            ) : (
              filteredSessions.map((s) => {
                const isSelected = s.session_id === selectedSessionId
                return (
                  <div
                    key={s.session_id}
                    onClick={() => {
                      setSelectedSessionId(s.session_id)
                      onSelectSession?.(s.session_id)
                    }}
                    style={{
                      padding: '8px 10px',
                      borderBottom: '1px solid #f1f5f9',
                      cursor: 'pointer',
                      background: isSelected ? '#eff6ff' : 'transparent',
                      borderLeft: isSelected ? '3px solid #2563eb' : '3px solid transparent',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 600, fontSize: 11, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 110 }}>
                        {s.session_id}
                      </span>
                      <span style={{ fontSize: 10, background: '#e2e8f0', color: '#475569', padding: '1px 4px', borderRadius: 3 }}>
                        {s.message_count} msgs
                      </span>
                    </div>
                    {s.first_prompt && (
                      <div style={{ fontSize: 11, color: '#64748b', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.first_prompt}
                      </div>
                    )}
                    <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 3, display: 'flex', justifyContent: 'space-between' }}>
                      <span>~{s.total_tokens} tokens</span>
                      <span>{new Date(s.last_updated).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Right: Message Turns detail */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#f8fafc', overflow: 'hidden' }}>
          {selectedSessionId ? (
            <>
              <div style={{ padding: '8px 12px', borderBottom: '1px solid #e2e8f0', background: '#ffffff', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 12, color: '#334155', wordBreak: 'break-all' }}>
                  Session: <code style={{ fontSize: 11, color: '#2563eb' }}>{selectedSessionId}</code>
                </span>
                <button
                  type="button"
                  onClick={() => handleClearSession(selectedSessionId)}
                  style={{ padding: '2px 8px', borderRadius: 4, background: '#fee2e2', border: '1px solid #fecaca', color: '#b91c1c', fontSize: 11, cursor: 'pointer' }}
                >
                  Clear Session
                </button>
              </div>

              <div style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {loading ? (
                  <div style={{ padding: 14, textAlign: 'center', color: '#64748b' }}>Loading messages…</div>
                ) : messages.length === 0 ? (
                  <div style={{ padding: 14, textAlign: 'center', color: '#94a3b8' }}>No turns in this session.</div>
                ) : (
                  messages.map((m, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: 8,
                        borderRadius: 6,
                        border: '1px solid',
                        borderColor: m.role === 'user' ? '#bfdbfe' : '#e2e8f0',
                        background: m.role === 'user' ? '#eff6ff' : '#ffffff',
                        position: 'relative',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <span style={{ fontWeight: 600, fontSize: 11, color: m.role === 'user' ? '#1d4ed8' : '#059669', textTransform: 'uppercase' }}>
                          {m.role === 'user' ? '👤 User' : '🤖 Assistant'}
                        </span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ fontSize: 10, color: '#94a3b8' }}>~{m.token_count} tok</span>
                          <button
                            type="button"
                            title="Prune this turn"
                            onClick={() => handleDeleteMessage(idx)}
                            style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: 11, color: '#94a3b8', padding: 0 }}
                          >
                            ✕
                          </button>
                        </div>
                      </div>
                      <div style={{ fontSize: 12, color: '#334155', whiteSpace: 'pre-wrap', maxHeight: 180, overflowY: 'auto' }}>
                        {m.content}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </>
          ) : (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8' }}>
              Select a session on the left to inspect turns
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
