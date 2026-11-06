import { useSyncExternalStore } from 'react'

/**
 * Recently dropped canvas nodes, shown at the bottom of the sidebar.
 * Each entry keeps the full drag payload (every dataTransfer type) so dragging
 * it again recreates exactly the same node, whatever sidebar section it came from.
 */
export interface RecentNode {
  label: string
  type: string
  payload: Record<string, string>
}

const STORAGE_KEY = 'univ.recentNodes.v1'
const MAX_RECENT = 5

function readRecent(): RecentNode[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(parsed)
      ? parsed.filter((r) => r && typeof r.label === 'string' && r.payload && typeof r.payload === 'object')
      : []
  } catch {
    return []
  }
}

let recent: RecentNode[] = readRecent()
const listeners = new Set<() => void>()

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

function getRecent(): readonly RecentNode[] {
  return recent
}

export function recordRecentNode(label: string, type: string, dataTransfer: DataTransfer) {
  const payload: Record<string, string> = {}
  for (const t of dataTransfer.types) {
    if (t.startsWith('application/univ-')) payload[t] = dataTransfer.getData(t)
  }
  if (Object.keys(payload).length === 0) return
  const key = JSON.stringify(payload)
  recent = [{ label, type, payload }, ...recent.filter((r) => JSON.stringify(r.payload) !== key)].slice(0, MAX_RECENT)
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(recent)) } catch { /* storage unavailable */ }
  listeners.forEach((fn) => fn())
}

export function useRecentNodes(): readonly RecentNode[] {
  return useSyncExternalStore(subscribe, getRecent, getRecent)
}
