import { API_BASE } from '../types'

/** Release notes for the "What's new" panel (GET /api/release-notes) and which release this browser has seen. */
export interface ReleaseFile { path: string; added: number; removed: number }
export interface ReleaseArea { area: string; files: number; added: number; removed: number }
export interface ReleaseCommit {
  hash: string
  short: string
  date: string
  author: string
  subject: string
  body: string
  files: ReleaseFile[]
  areas: ReleaseArea[]
}
export interface ReleaseNotes { source: 'git' | 'build' | 'none'; commits: ReleaseCommit[] }

const SEEN_KEY = 'pipesets:release-notes-seen'

export function lastSeenRelease(): string {
  try { return localStorage.getItem(SEEN_KEY) || '' } catch { return '' }
}

export function markReleaseSeen(hash: string) {
  try { localStorage.setItem(SEEN_KEY, hash) } catch { /* private mode: the dot just comes back */ }
}

export async function fetchReleaseNotes(limit = 1): Promise<ReleaseNotes> {
  const res = await fetch(`${API_BASE}/api/release-notes?limit=${limit}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
