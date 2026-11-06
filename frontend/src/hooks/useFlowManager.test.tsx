import { act, renderHook } from '@testing-library/react'
import { ReactFlowProvider } from '@xyflow/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import type { AppRecord, FlowEdge, FlowNode } from '../types'
import { useFlowManager } from './useFlowManager'

const node = (id: string, extra: Partial<FlowNode> = {}): FlowNode =>
  ({ id, type: 'llm', position: { x: 10, y: 20 }, data: { label: id, cfg: { n: 1 } }, ...extra }) as unknown as FlowNode
const edge = (source: string, target: string): FlowEdge =>
  ({ id: `${source}-${target}`, source, target }) as FlowEdge

const wrapper = ({ children }: { children: ReactNode }) => <ReactFlowProvider>{children}</ReactFlowProvider>

function setup(nodes: FlowNode[], edges: FlowEdge[] = []) {
  const hook = renderHook(() => useFlowManager(), { wrapper })
  act(() => hook.result.current.loadFlow({ id: 'app', flow_data: { nodes, edges } } as unknown as AppRecord))
  return hook
}

describe('useFlowManager', () => {
  it('loadFlow selects the first node', () => {
    const { result } = setup([node('a'), node('b')])
    expect(result.current.selectedNodeId).toBe('a')
    expect(result.current.activeNode?.id).toBe('a')
  })

  it('deleteNode drops the node, its edges and the selection', () => {
    const { result } = setup([node('a'), node('b'), node('c')], [edge('a', 'b'), edge('b', 'c'), edge('a', 'c')])
    act(() => result.current.deleteNode('a'))
    expect(result.current.nodes.map((n) => n.id)).toEqual(['b', 'c'])
    expect(result.current.edges.map((e) => e.id)).toEqual(['b-c'])
    expect(result.current.selectedNodeId).toBeNull()
  })

  it('updateNodeData merges fields into one node only', () => {
    const { result } = setup([node('a'), node('b')])
    act(() => result.current.updateNodeData('b', { label: 'renamed', model: 'x' }))
    expect(result.current.nodes[1].data).toMatchObject({ label: 'renamed', model: 'x', cfg: { n: 1 } })
    expect(result.current.nodes[0].data.label).toBe('a')
  })

  it('copy + paste duplicates the selection with new ids, offset, and only internal edges', () => {
    const { result } = setup(
      [node('a', { selected: true }), node('b', { selected: true }), node('c')],
      [edge('a', 'b'), edge('b', 'c')],
    )
    let copied = false
    act(() => { copied = result.current.copySelection() })
    expect(copied).toBe(true)
    act(() => { result.current.paste() })

    const { nodes, edges } = result.current
    expect(nodes).toHaveLength(5)
    const pasted = nodes.slice(3)
    expect(pasted.map((n) => n.data.label)).toEqual(['a', 'b'])
    expect(pasted.every((n) => n.selected && !['a', 'b'].includes(n.id))).toBe(true)
    expect(pasted[0].position).toEqual({ x: 50, y: 60 })
    // Originals lose the selection; pasted node becomes active
    expect(nodes.slice(0, 3).some((n) => n.selected)).toBe(false)
    expect(result.current.selectedNodeId).toBe(pasted[0].id)

    expect(edges).toHaveLength(3)
    expect(edges[2]).toMatchObject({ source: pasted[0].id, target: pasted[1].id })
  })

  it('pasted data is a deep copy, and repeated pastes step further out', () => {
    const { result } = setup([node('a')])
    act(() => { result.current.copySelection() })  // falls back to the selected node
    act(() => { result.current.paste() })
    act(() => { result.current.paste() })

    const [orig, first, second] = result.current.nodes
    const cfg = (n: FlowNode) => (n.data as Record<string, unknown>).cfg
    expect(cfg(first)).toEqual(cfg(orig))
    expect(cfg(first)).not.toBe(cfg(orig))
    expect(typeof first.data.onDelete).toBe('function')
    expect(second.position).toEqual({ x: 90, y: 100 })
  })

  it('copy with nothing selected, or paste with an empty clipboard, does nothing', () => {
    const { result } = setup([])
    let ok = true
    act(() => { ok = result.current.copySelection() })
    expect(ok).toBe(false)
    act(() => { ok = result.current.paste() })
    expect(ok).toBe(false)
  })
})
