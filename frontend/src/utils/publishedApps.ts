import { useEffect, useSyncExternalStore } from 'react'
import { API_BASE } from '../types'
import type { AppRecord } from '../types'

/**
 * Shared cache of apps that have at least one published version. Pipeline child
 * nodes read it to flag "newer version available" without each card fetching.
 */
const STALE_MS = 15_000

let apps: AppRecord[] = []
let loading = false
let fetchedAt = 0
let inflight: Promise<void> | null = null
const listeners = new Set<() => void>()

function emit() { listeners.forEach((fn) => fn()) }

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

export function refreshPublishedApps(): Promise<void> {
  if (inflight) return inflight
  loading = true
  emit()
  inflight = fetch(`${API_BASE}/api/apps`)
    .then((r) => (r.ok ? r.json() : []))
    .then((rows: AppRecord[]) => { apps = rows.filter((a) => (a.version ?? 0) > 0) })
    .catch(() => { apps = [] })
    .finally(() => {
      loading = false
      fetchedAt = Date.now()
      inflight = null
      emit()
    })
  return inflight
}

const getApps = () => apps
const getLoading = () => loading

/** Apps with ≥1 published version; refetches when the cache is stale. */
export function usePublishedApps(): { apps: readonly AppRecord[]; loading: boolean } {
  useEffect(() => {
    if (Date.now() - fetchedAt > STALE_MS) refreshPublishedApps()
  }, [])
  return {
    apps: useSyncExternalStore(subscribe, getApps, getApps),
    loading: useSyncExternalStore(subscribe, getLoading, getLoading),
  }
}

/** Latest published version of an app, or undefined while unknown. */
export function useLatestAppVersion(appId: string | undefined): number | undefined {
  const { apps: list } = usePublishedApps()
  return appId ? list.find((a) => a.id === appId)?.version : undefined
}

export interface AppVersionInfo {
  version: number
  name: string
  description: string
  node_count: number
  created_at: string
}

export async function fetchAppVersions(appId: string): Promise<AppVersionInfo[]> {
  const r = await fetch(`${API_BASE}/api/apps/${encodeURIComponent(appId)}/versions`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}
