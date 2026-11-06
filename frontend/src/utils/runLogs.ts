/**
 * runLogs — global store of pipeline run logs.
 * Every run started from the Run panel writes here, tagged with its runId and pipeline (app),
 * so the Run panel, per-run views and the global Logs tab all read the same data.
 * Persisted in localStorage (capped) so logs survive reloads.
 */
import { useSyncExternalStore } from 'react'

export type RunLogLevel = 'info' | 'ok' | 'tool' | 'warn' | 'error'

export interface RunLogEntry {
  id: number
  ts: number
  level: RunLogLevel
  source: string
  message: string
  runId: string
  appId: string
  appName: string
}

const STORAGE_KEY = 'univ.runLogs.v1'
const MAX_ENTRIES = 2000

function load(): RunLogEntry[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(parsed) ? parsed.slice(-MAX_ENTRIES) : []
  } catch {
    return []
  }
}

let entries: readonly RunLogEntry[] = load()
let nextId = entries.reduce((m, e) => Math.max(m, e.id), 0) + 1
const listeners = new Set<() => void>()
let persistTimer: ReturnType<typeof setTimeout> | undefined

function persist() {
  clearTimeout(persistTimer)
  persistTimer = setTimeout(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(entries)) } catch { /* storage unavailable */ }
  }, 300)
}

function commit(next: readonly RunLogEntry[]) {
  entries = next
  persist()
  listeners.forEach((fn) => fn())
}

export function addRunLog(
  entry: Omit<RunLogEntry, 'id' | 'ts'>,
) {
  const next = [...entries, { ...entry, id: nextId++, ts: Date.now() }]
  commit(next.length > MAX_ENTRIES ? next.slice(-MAX_ENTRIES) : next)
}

/** Clear every log, or only the logs of one pipeline (app). */
export function clearRunLogs(appId?: string) {
  commit(appId === undefined ? [] : entries.filter((e) => e.appId !== appId))
}

export function newRunId() {
  return `run-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

const getSnapshot = () => entries

export function useRunLogs(): readonly RunLogEntry[] {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

export function fmtLogTime(ts: number) {
  const d = new Date(ts)
  return `${d.toTimeString().slice(0, 8)}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

export function fmtLogDateTime(ts: number) {
  const d = new Date(ts)
  return `${d.toLocaleDateString()} ${fmtLogTime(ts)}`
}

export function logsToText(list: readonly RunLogEntry[]) {
  return list
    .map((l) => `${fmtLogDateTime(l.ts)} [${l.level.toUpperCase()}] ${l.appName || l.appId || '-'} ${l.runId} ${l.source}: ${l.message}`)
    .join('\n')
}
