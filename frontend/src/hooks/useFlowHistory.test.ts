import { act, renderHook } from '@testing-library/react'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FlowEdge, FlowNode } from '../types'
import { useFlowHistory } from './useFlowHistory'

const node = (id: string, extra: Partial<FlowNode> = {}, data: Record<string, unknown> = {}): FlowNode =>
  ({ id, type: 'llm', position: { x: 0, y: 0 }, data: { label: id, ...data }, ...extra }) as unknown as FlowNode

/** The hook wired to real canvas state, as useFlowManager does. */
function useCanvas(initial: FlowNode[] = []) {
  const [nodes, setNodes] = useState<FlowNode[]>(initial)
  const [edges, setEdges] = useState<FlowEdge[]>([])
  return { nodes, setNodes, edges, setEdges, ...useFlowHistory(nodes, edges, setNodes, setEdges) }
}

const settle = () => act(() => { vi.advanceTimersByTime(300) })
const labels = (nodes: FlowNode[]) => nodes.map((n) => n.data.label)

beforeEach(() => { vi.useFakeTimers() })

describe('useFlowHistory', () => {
  it('records settled edits and walks them back and forward', () => {
    const { result } = renderHook(() => useCanvas([node('a')]))
    settle()
    expect(result.current.canUndo).toBe(false)

    act(() => result.current.setNodes((n) => [...n, node('b')]))
    settle()
    act(() => result.current.setNodes((n) => [...n, node('c')]))
    settle()
    expect(result.current.canUndo).toBe(true)

    act(() => result.current.undo())
    expect(labels(result.current.nodes)).toEqual(['a', 'b'])
    act(() => result.current.undo())
    expect(labels(result.current.nodes)).toEqual(['a'])
    expect(result.current.canUndo).toBe(false)
    expect(result.current.canRedo).toBe(true)

    act(() => result.current.redo())
    expect(labels(result.current.nodes)).toEqual(['a', 'b'])
  })

  it('folds edits inside the settle window into one entry', () => {
    const { result } = renderHook(() => useCanvas([node('a')]))
    settle()
    act(() => result.current.setNodes((n) => [...n, node('b')]))
    act(() => { vi.advanceTimersByTime(100) })
    act(() => result.current.setNodes((n) => [...n, node('c')]))
    settle()

    act(() => result.current.undo())
    expect(labels(result.current.nodes)).toEqual(['a'])
  })

  it('ignores selection, drag and connection status changes', () => {
    const { result } = renderHook(() => useCanvas([node('a')]))
    settle()
    act(() => result.current.setNodes([node('a', { selected: true }, { status: 'ok', status_msg: 'live' })]))
    settle()
    expect(result.current.canUndo).toBe(false)
  })

  it('skips snapshots while a node is being dragged', () => {
    const { result } = renderHook(() => useCanvas([node('a')]))
    settle()
    act(() => result.current.setNodes([node('a', { dragging: true, position: { x: 50, y: 0 } })]))
    settle()
    expect(result.current.canUndo).toBe(false)

    act(() => result.current.setNodes([node('a', { dragging: false, position: { x: 50, y: 0 } })]))
    settle()
    expect(result.current.canUndo).toBe(true)
  })

  it('undo right after an edit still restores the state before it', () => {
    const { result } = renderHook(() => useCanvas([node('a')]))
    settle()
    act(() => result.current.setNodes((n) => [...n, node('b')]))
    // No settle: undo flushes the pending edit first
    act(() => result.current.undo())
    expect(labels(result.current.nodes)).toEqual(['a'])
    expect(result.current.canRedo).toBe(true)
  })

  it('a new edit clears redo', () => {
    const { result } = renderHook(() => useCanvas([node('a')]))
    settle()
    act(() => result.current.setNodes((n) => [...n, node('b')]))
    settle()
    act(() => result.current.undo())
    act(() => result.current.setNodes((n) => [...n, node('z')]))
    settle()
    expect(result.current.canRedo).toBe(false)
  })

  it('reset() starts the next loaded flow with empty history', () => {
    const { result } = renderHook(() => useCanvas([node('a')]))
    settle()
    act(() => result.current.setNodes((n) => [...n, node('b')]))
    settle()

    act(() => {
      result.current.reset()
      result.current.setNodes([node('other')])
    })
    settle()
    expect(result.current.canUndo).toBe(false)
    expect(result.current.canRedo).toBe(false)
  })

  it('keeps at most 100 undo steps', () => {
    const { result } = renderHook(() => useCanvas([node('n0')]))
    settle()
    for (let i = 1; i <= 105; i++) {
      act(() => result.current.setNodes([node(`n${i}`)]))
      settle()
    }
    let steps = 0
    while (result.current.canUndo) {
      act(() => result.current.undo())
      steps++
    }
    expect(steps).toBe(100)
    expect(labels(result.current.nodes)).toEqual(['n5'])
  })
})
