import { useMemo, useSyncExternalStore } from 'react'
import type { ToolCatalogItem, ToolCategory } from '../types'

/**
 * The tool catalog from GET /api/tools, shared outside React props. Each built-in tool's
 * spec (backend/tools/) carries its dropdown settings (`config_options`) and the keys it
 * can't run without (`required_config`) — the frontend reads them from here.
 */
let byId = new Map<string, ToolCatalogItem>()
let version = 0
const listeners = new Set<() => void>()

export function setToolCatalog(categories: ToolCategory[]) {
  byId = new Map(categories.flatMap((c) => c.tools).map((t) => [t.id, t]))
  version += 1
  listeners.forEach((fn) => fn())
}

export const getToolSpec = (toolId: string): ToolCatalogItem | undefined => byId.get(toolId)

export const requiredConfigFor = (toolId: string): string[] => byId.get(toolId)?.required_config ?? []

/** A requiredConfigFor() whose identity changes when the catalog loads — pass it to validatePipeline. */
export function useRequiredConfig(): (toolId: string) => string[] {
  const v = useToolCatalogVersion()
  return useMemo(() => {
    void v
    return (toolId: string) => requiredConfigFor(toolId)
  }, [v])
}

/** Re-renders when the catalog loads. */
export function useToolCatalogVersion(): number {
  return useSyncExternalStore(
    (fn) => { listeners.add(fn); return () => { listeners.delete(fn) } },
    () => version,
    () => version,
  )
}
