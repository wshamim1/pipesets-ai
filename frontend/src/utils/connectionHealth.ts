import { API_BASE } from '../types'
import type { ConnectionNodeData } from '../types'

export type ConnectionHealth = Pick<ConnectionNodeData, 'status' | 'status_msg'>

// Re-runs the backend health check for a saved connection (it also persists the result)
export async function retestConnection(connectionId: string): Promise<ConnectionHealth> {
  try {
    const res = await fetch(`${API_BASE}/api/connections/${encodeURIComponent(connectionId)}/test`, { method: 'POST' })
    if (!res.ok) return { status: 'error', status_msg: `Health check failed (HTTP ${res.status})` }
    const result = await res.json()
    return {
      status: (result.status ?? 'untested') as ConnectionNodeData['status'],
      status_msg: result.message ?? '',
    }
  } catch {
    return { status: 'error', status_msg: 'Could not reach the backend to test this connection.' }
  }
}
