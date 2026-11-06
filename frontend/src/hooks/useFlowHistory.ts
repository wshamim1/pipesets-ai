import { useCallback, useEffect, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { FlowNode, FlowEdge } from '../types'

const LIMIT = 100
const SETTLE_MS = 300

type Snapshot = { nodes: FlowNode[]; edges: FlowEdge[]; key: string }

// Fields that change without being an edit: selection, drag state, measured size,
// and connection health (refreshed live from the backend).
// Callbacks (onDelete, onDropTool) are re-attached by App and skipped as functions.
const TRANSIENT = new Set(['selected', 'dragging', 'measured', 'resizing', 'isSelected', 'status', 'status_msg'])

function keyOf(nodes: FlowNode[], edges: FlowEdge[]): string {
  return JSON.stringify({ nodes, edges }, (k, v) => (typeof v === 'function' || TRANSIENT.has(k) ? undefined : v))
}

/**
 * Undo/redo for the canvas. Instead of instrumenting every mutation, it watches
 * nodes/edges and records a snapshot once they settle, ignoring selection and
 * drag noise — so drops, deletes, connects, moves and config edits are all covered.
 * Call reset() before loading a different flow so its history starts empty.
 */
export function useFlowHistory(
  nodes: FlowNode[],
  edges: FlowEdge[],
  setNodes: Dispatch<SetStateAction<FlowNode[]>>,
  setEdges: Dispatch<SetStateAction<FlowEdge[]>>,
) {
  const past = useRef<Snapshot[]>([])
  const future = useRef<Snapshot[]>([])
  const current = useRef<Snapshot | null>(null)
  const pendingReset = useRef(false)
  const latest = useRef({ nodes, edges })
  latest.current = { nodes, edges }
  const [, rerender] = useState(0)

  // Commit the live state as a new history entry if it differs from `current`.
  const record = useCallback(() => {
    const { nodes: n, edges: e } = latest.current
    if (n.some((node) => node.dragging)) return
    const key = keyOf(n, e)
    if (pendingReset.current) {
      pendingReset.current = false
      past.current = []
      future.current = []
    } else if (current.current?.key === key) {
      return
    } else if (current.current) {
      past.current = [...past.current.slice(-(LIMIT - 1)), current.current]
      future.current = []
    }
    current.current = { nodes: n, edges: e, key }
    rerender((x) => x + 1)
  }, [])

  useEffect(() => {
    const t = setTimeout(record, SETTLE_MS)
    return () => clearTimeout(t)
  }, [nodes, edges, record])

  const restore = useCallback((from: { current: Snapshot[] }, to: { current: Snapshot[] }) => {
    record() // flush an edit made within the settle window so it isn't skipped
    const target = from.current.pop()
    if (!target || !current.current) return
    to.current.push(current.current)
    current.current = target
    // Update `latest` now so a second undo before React re-renders doesn't
    // mistake the pre-undo state for a fresh edit.
    latest.current = { nodes: target.nodes, edges: target.edges }
    setNodes(target.nodes)
    setEdges(target.edges)
    rerender((x) => x + 1)
  }, [record, setNodes, setEdges])

  const undo = useCallback(() => restore(past, future), [restore])
  const redo = useCallback(() => restore(future, past), [restore])
  const reset = useCallback(() => { pendingReset.current = true }, [])

  return { undo, redo, reset, canUndo: past.current.length > 0, canRedo: future.current.length > 0 }
}
