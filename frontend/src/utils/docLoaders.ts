import { useSyncExternalStore } from 'react'

/**
 * Document Loader types. The built-in catalog comes from the backend registry
 * (backend/loaders/, served by GET /api/retrieval/loaders) and is loaded at startup;
 * user-defined custom loaders are kept in localStorage.
 * Used by the sidebar, canvas node, config panel, drop handler and blueprint importer.
 */
export interface DocLoaderDef {
  type: string
  label: string
  icon: string
  desc: string
  /** Sidebar group, e.g. "Files", "Web & Feeds". */
  category?: string
  /** Label of the "source" input in the config panel. */
  sourceLabel: string
  placeholder: string
  /** True when the source is a document the user can upload (shows the upload dropzone). */
  fileBased?: boolean
  /** Credentials come from a Connection node wired to the loader. */
  usesConnection?: boolean
  /** False for loaders listed in the catalog but not built yet ("Soon"). */
  available?: boolean
  /** Extra names an LLM / code importer may use for this loader. */
  aliases?: string[]
  /** True for user-defined loaders (type is prefixed with `custom_`). */
  custom?: boolean
  /** Custom loaders: import path / class name, e.g. `my_pkg.loaders.MyLoader`. */
  loaderClass?: string
  /** Custom loaders: JSON object of constructor kwargs. */
  loaderKwargs?: string
}

/** Built-in loader ids, plus any user-defined `custom_*` id. */
export type DocLoaderType = string

let builtIn: DocLoaderDef[] = []
let BY_TYPE: Record<string, DocLoaderDef> = {}
/** Lower-cased, separator-free alias → canonical loader type. */
let ALIAS_MAP: Record<string, string> = {}

/** DB-backed loaders: credentials come from a Connection node wired to the loader, not a pasted DSN.
 * Refilled from the catalog's `usesConnection` flags when it loads. */
export const DB_LOADER_TYPES: Set<string> = new Set(['postgres', 'mysql', 'mongodb', 'snowflake', 'sql_database'])

const norm = (s: string) => s.toLowerCase().replace(/[\s_-]+/g, '')

/** Install the catalog from GET /api/retrieval/loaders. */
export function setDocLoaderCatalog(loaders: DocLoaderDef[]) {
  builtIn = loaders
  BY_TYPE = Object.fromEntries(loaders.map((d) => [d.type, d]))
  ALIAS_MAP = {}
  for (const d of loaders) for (const a of d.aliases ?? []) ALIAS_MAP[norm(a)] ??= d.type
  for (const d of loaders) ALIAS_MAP[norm(d.type)] = d.type   // a loader's own name beats another's alias
  DB_LOADER_TYPES.clear()
  for (const d of loaders) if (d.usesConnection) DB_LOADER_TYPES.add(d.type)
  notify()
}

// ── Custom (user-defined) loaders, persisted in localStorage ──
const CUSTOM_STORAGE_KEY = 'univ.customDocLoaders.v1'

function readCustomLoaders(): DocLoaderDef[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(CUSTOM_STORAGE_KEY) ?? '[]')
    return Array.isArray(parsed)
      ? parsed.filter((d) => d && typeof d.type === 'string' && d.type.startsWith('custom_')).map((d) => ({ ...d, custom: true }))
      : []
  } catch {
    return []
  }
}

let customLoaders: DocLoaderDef[] = readCustomLoaders()
const listeners = new Set<() => void>()
let allSnapshot: readonly DocLoaderDef[] = [...customLoaders]

function notify() {
  allSnapshot = [...customLoaders, ...builtIn]
  listeners.forEach((fn) => fn())
}

function commitCustomLoaders(next: DocLoaderDef[]) {
  customLoaders = next
  try { localStorage.setItem(CUSTOM_STORAGE_KEY, JSON.stringify(next)) } catch { /* storage unavailable */ }
  notify()
}

function subscribeCustomDocLoaders(fn: () => void) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

export function getCustomDocLoaders(): readonly DocLoaderDef[] {
  return customLoaders
}

/** React hook: re-renders when custom loaders are added / edited / removed. */
export function useCustomDocLoaders(): readonly DocLoaderDef[] {
  return useSyncExternalStore(subscribeCustomDocLoaders, getCustomDocLoaders, getCustomDocLoaders)
}

/** React hook: custom loaders first, then the built-in catalog (re-renders when either changes). */
export function useDocLoaders(): readonly DocLoaderDef[] {
  return useSyncExternalStore(subscribeCustomDocLoaders, () => allSnapshot, () => allSnapshot)
}

/** Insert or update (matched by `type`) a custom loader. Returns the stored definition. */
export function saveCustomDocLoader(def: Omit<DocLoaderDef, 'type' | 'custom'> & { type?: string }): DocLoaderDef {
  let type = def.type
  if (!type) {
    const slug = def.label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'loader'
    type = `custom_${slug}`
    for (let i = 2; BY_TYPE[type] || customLoaders.some((d) => d.type === type); i++) type = `custom_${slug}_${i}`
  }
  const saved: DocLoaderDef = { ...def, type, custom: true }
  commitCustomLoaders(
    customLoaders.some((d) => d.type === type)
      ? customLoaders.map((d) => (d.type === type ? saved : d))
      : [...customLoaders, saved],
  )
  return saved
}

export function deleteCustomDocLoader(type: string) {
  commitCustomLoaders(customLoaders.filter((d) => d.type !== type))
}

export function getDocLoader(type: string | undefined): DocLoaderDef | undefined {
  if (!type) return undefined
  return BY_TYPE[type] ?? customLoaders.find((d) => d.type === type)
}

/** Default node label when a loader is dropped on the canvas. */
export function docLoaderNodeLabel(type: string): string {
  const def = getDocLoader(type)
  if (!def) return 'Document Loader'
  return def.label.endsWith('Loader') ? def.label : `${def.label} Loader`
}

export function resolveDocLoaderType(raw: unknown, source?: unknown): string {
  const key = norm(String(raw ?? ''))
  if (ALIAS_MAP[key]) return ALIAS_MAP[key]
  if (/^https?:\/\//i.test(String(source ?? ''))) return 'web_url'
  return (typeof raw === 'string' && raw) || 'pdf'
}

export function docLoaderSourceLabel(type: string): string {
  return getDocLoader(type)?.sourceLabel ?? 'Source'
}
