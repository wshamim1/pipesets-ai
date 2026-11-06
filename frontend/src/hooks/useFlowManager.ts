import { useState, useCallback, useRef } from 'react'
import { applyNodeChanges, applyEdgeChanges, addEdge, useReactFlow } from '@xyflow/react'
import type { NodeChange, Connection } from '@xyflow/react'
import type { FlowNode, FlowEdge, AppRecord } from '../types'
import { useFlowHistory } from './useFlowHistory'

const PASTE_OFFSET = 40

export function useFlowManager() {
  const [nodes, setNodes] = useState<FlowNode[]>([])
  const [edges, setEdges] = useState<FlowEdge[]>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const { screenToFlowPosition } = useReactFlow()
  const history = useFlowHistory(nodes, edges, setNodes, setEdges)
  const resetHistory = history.reset

  const loadFlow = useCallback((app: AppRecord) => {
    const flowNodes = app.flow_data?.nodes || []
    const flowEdges = app.flow_data?.edges || []
    resetHistory()
    setNodes(flowNodes)
    setEdges(flowEdges)
    setSelectedNodeId(flowNodes.length > 0 ? flowNodes[0].id : null)
    // Framing the loaded flow is left to <FitViewOnOpen>, which waits for the canvas to settle
  }, [resetHistory])

  const deleteNode = useCallback((nodeId: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId))
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId))
    setSelectedNodeId((curr) => (curr === nodeId ? null : curr))
  }, [])

  const updateNodeData = useCallback((nodeId: string, fields: Record<string, any>) => {
    setNodes((nds) =>
      nds.map((node) =>
        node.id === nodeId ? { ...node, data: { ...node.data, ...fields } } : node
      )
    )
  }, [])

  const onNodesChange = useCallback(
    (changes: NodeChange<FlowNode>[]) =>
      setNodes((nds) => applyNodeChanges<FlowNode>(changes, nds)),
    []
  )

  const onEdgesChange = useCallback(
    (changes: Parameters<typeof applyEdgeChanges>[0]) =>
      setEdges((eds) => applyEdgeChanges<FlowEdge>(changes, eds)),
    []
  )

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge(connection, eds)),
    [],
  )

  const onNodeClick = useCallback((_: React.MouseEvent, node: FlowNode) => {
    setSelectedNodeId(node.id)
  }, [])

  // ── Copy / paste ───────────────────────────────────────────────────────────
  // In-app clipboard: the selected nodes plus the edges between them.
  const clipboard = useRef<{ nodes: FlowNode[]; edges: FlowEdge[] } | null>(null)
  const pasteCount = useRef(0)

  const copySelection = useCallback((): boolean => {
    let picked = nodes.filter((n) => n.selected)
    if (picked.length === 0) picked = nodes.filter((n) => n.id === selectedNodeId)
    if (picked.length === 0) return false
    const ids = new Set(picked.map((n) => n.id))
    clipboard.current = { nodes: picked, edges: edges.filter((e) => ids.has(e.source) && ids.has(e.target)) }
    pasteCount.current = 0
    return true
  }, [nodes, edges, selectedNodeId])

  const paste = useCallback((): boolean => {
    const clip = clipboard.current
    if (!clip) return false
    pasteCount.current += 1
    const offset = PASTE_OFFSET * pasteCount.current
    const stamp = Date.now()
    const idMap = new Map(clip.nodes.map((n, i) => [n.id, `node-${stamp}-${i}`]))
    const pastedNodes: FlowNode[] = clip.nodes.map((n) => {
      const id = idMap.get(n.id)!
      // JSON round-trip deep-copies the data and drops callbacks; App re-attaches them.
      const data = JSON.parse(JSON.stringify(n.data))
      return {
        ...n, id, selected: true, dragging: false,
        position: { x: n.position.x + offset, y: n.position.y + offset },
        data: { ...data, onDelete: () => deleteNode(id) },
      } as FlowNode
    })
    const pastedEdges: FlowEdge[] = clip.edges.map((e, i) => ({
      ...e, id: `edge-${stamp}-${i}`, selected: false,
      source: idMap.get(e.source)!, target: idMap.get(e.target)!,
    }))
    setNodes((nds) => [...nds.map((n) => (n.selected ? { ...n, selected: false } : n)), ...pastedNodes])
    setEdges((eds) => [...eds.map((e) => (e.selected ? { ...e, selected: false } : e)), ...pastedEdges])
    setSelectedNodeId(pastedNodes[0].id)
    return true
  }, [deleteNode])

  const activeNode = nodes.find((n) => n.id === selectedNodeId) ?? nodes[0] ?? null

  return {
    nodes, setNodes,
    edges, setEdges,
    selectedNodeId, setSelectedNodeId,
    activeNode,
    loadFlow,
    deleteNode,
    updateNodeData,
    onNodesChange,
    onEdgesChange,
    onConnect,
    onNodeClick,
    screenToFlowPosition,
    undo: history.undo,
    redo: history.redo,
    canUndo: history.canUndo,
    canRedo: history.canRedo,
    copySelection,
    paste,
  }
}
