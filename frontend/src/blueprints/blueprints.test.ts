import { describe, expect, it } from 'vitest'
import { STARTER_BLUEPRINTS, buildBlueprintFlow } from './index'

const CALLERS = new Set(['llm', 'child_agent', 'wf_step'])   // nodes that call the tools wired to them

// Every handle id the node components declare
const nodeSources = import.meta.glob<string>('../nodes/*.tsx', { query: '?raw', import: 'default', eager: true })
const HANDLE_IDS = new Set(Object.values(nodeSources).flatMap((src) => [...src.matchAll(/<Handle[^>]*\bid="([^"]+)"/g)].map((m) => m[1])))

describe('starter blueprints', () => {
  it('are found one per file, with unique ids and orders, in gallery order', () => {
    const ids = STARTER_BLUEPRINTS.map((b) => b.id)
    expect(ids.length).toBe(33)
    expect(new Set(ids).size).toBe(ids.length)
    expect(new Set(STARTER_BLUEPRINTS.map((b) => b.order)).size).toBe(ids.length)
    expect(ids.slice(0, 3)).toEqual(['tpl-rag', 'tpl-multi-agent', 'tpl-tool-agent'])
    expect(() => buildBlueprintFlow('tpl-nope')).toThrow('Unknown blueprint')
  })

  it.each(STARTER_BLUEPRINTS.map((b) => [b.id]))('%s is wired correctly', (id) => {
    const { nodes, edges } = buildBlueprintFlow(id)
    const byId = new Map(nodes.map((n) => [n.id, n]))
    expect(byId.size, 'unique node ids').toBe(nodes.length)
    expect(nodes.some((n) => n.type === 'start')).toBe(true)
    for (const e of edges) {
      expect(byId.has(e.source) && byId.has(e.target), `edge ${e.id} points at real nodes`).toBe(true)
      // Without explicit handles React Flow uses each node's first (left) handle and the edge loops round its source
      expect(HANDLE_IDS.has(e.sourceHandle ?? ''), `edge ${e.id} source handle ${e.sourceHandle}`).toBe(true)
      expect(HANDLE_IDS.has(e.targetHandle ?? ''), `edge ${e.id} target handle ${e.targetHandle}`).toBe(true)
    }
    expect(new Set(edges.map((e) => e.id)).size, 'unique edge ids').toBe(edges.length)
    // An LLM's tools, memory, skills… sit in a row above or below it, not on the Start → LLM → Stop line where
    // they'd read as the next step
    for (const e of edges) {
      const [s, t] = [byId.get(e.source)!, byId.get(e.target)!]
      const [llm, other] = s.type === 'llm' ? [s, t] : t.type === 'llm' ? [t, s] : []
      if (llm && other && !['start', 'stop', 'llm', 'retriever'].includes(other.type ?? '')) {
        expect(Math.abs(other.position.y - llm.position.y), `${other.id} is off ${llm.id}'s row`).toBeGreaterThanOrEqual(150)
      }
    }
    // A tool only runs when an LLM, child agent or workflow step it's wired to calls it
    for (const t of nodes.filter((n) => n.type === 'tool')) {
      const neighbours = edges.filter((e) => e.source === t.id || e.target === t.id)
        .map((e) => byId.get(e.source === t.id ? e.target : e.source)!)
      expect(neighbours.some((n) => CALLERS.has(n.type ?? '')), `${t.id} is wired to something that calls it`).toBe(true)
    }
  })
})
