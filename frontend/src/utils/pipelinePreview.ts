import { useSyncExternalStore } from 'react'

/**
 * Read-only preview of the pipeline a pipeline child calls. Kept as a stack so a
 * nested pipeline child inside the preview can be expanded too (breadcrumbs).
 */
export interface PipelinePreviewEntry {
  appId: string
  version: number   // 0 = latest published
  name: string
}

let stack: PipelinePreviewEntry[] = []
const listeners = new Set<() => void>()

function emit() { listeners.forEach((fn) => fn()) }

function subscribe(fn: () => void) {
  listeners.add(fn)
  return () => { listeners.delete(fn) }
}

const getStack = () => stack

/** Opens the preview, or drills one level deeper when it is already open. */
export function openPipelinePreview(entry: PipelinePreviewEntry) {
  stack = [...stack, entry]
  emit()
}

/** Pops back to the given breadcrumb depth (0 = first pipeline). */
export function popPipelinePreview(depth: number) {
  stack = stack.slice(0, depth + 1)
  emit()
}

export function closePipelinePreview() {
  stack = []
  emit()
}

export function usePipelinePreviewStack(): readonly PipelinePreviewEntry[] {
  return useSyncExternalStore(subscribe, getStack, getStack)
}
