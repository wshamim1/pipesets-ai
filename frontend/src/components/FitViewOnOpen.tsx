import { useEffect, useRef } from 'react'
import { useNodesInitialized, useReactFlow, useStore } from '@xyflow/react'

// The surrounding panels are still settling when the canvas mounts, so the
// built-in `fitView` prop fits to a stale size and the flow lands off to the
// top-left. Refit once nodes are measured, and again on resizes during a short
// settle window — after that the user owns the viewport. Nodes that only show up
// well after mount (first drop onto an empty canvas) are left alone.
const SETTLE_MS = 600
const LOAD_GRACE_MS = 1500
const FIT_OPTIONS = { maxZoom: 1, padding: 0.2 }

export function FitViewOnOpen() {
  const { fitView } = useReactFlow()
  const nodesInitialized = useNodesInitialized()
  const width = useStore((s) => s.width)
  const height = useStore((s) => s.height)
  const mountedAt = useRef(performance.now())
  const firstFitAt = useRef<number | null>(null)

  useEffect(() => {
    if (!nodesInitialized || !width || !height) return
    if (firstFitAt.current === null) {
      if (performance.now() - mountedAt.current > LOAD_GRACE_MS) return
      firstFitAt.current = performance.now()
    } else if (performance.now() - firstFitAt.current > SETTLE_MS) return
    const frame = requestAnimationFrame(() => { void fitView(FIT_OPTIONS) })
    return () => cancelAnimationFrame(frame)
  }, [nodesInitialized, width, height, fitView])

  return null
}
