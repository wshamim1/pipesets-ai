import { describe, expect, it } from 'vitest'
import type { FlowEdge, FlowNode } from '../types'
import { buildAgentSpec, instantiateSavedAgent } from './savedAgents'
import type { SavedAgent } from './savedAgents'

const n = (id: string, type: string, data: Record<string, unknown>) => ({ id, type, position: { x: 0, y: 0 }, data }) as unknown as FlowNode
const e = (source: string, target: string) => ({ id: `${source}-${target}`, source, target }) as FlowEdge

const canvas = [
  n('m', 'master_agent', { label: 'Master' }),
  n('c', 'child_agent', {
    label: 'SQL Analyst', master_id: 'm', role: 'Data Analyst', provider: 'openai', model: 'gpt-x', api_key: 'sk',
    system_prompt: 'Write SQL.', allowed_tool_ids: [], isSelected: true, onDelete: () => {},
    debug_pin: { output: 'x' }, saved_agent_id: 'old',
  }),
  n('t', 'tool', { label: 'SQL', toolId: 'sql_database', config: { read_only: true }, nodeId: 't', onDelete: () => {} }),
  n('k', 'toolkit', { label: 'Kit', toolkitId: 'tk', subTools: [{ toolId: 'calculator' }], onDropTool: () => {} }),
  n('s', 'skill', { label: 'Snowflake review', skill_id: 'skill_snowflake_query_review', skill_version: 2 }),
  n('other', 'tool', { label: 'Weather', toolId: 'weather' }),
]
const edges = [e('m', 'c'), e('c', 't'), e('k', 'c'), e('s', 'c'), e('m', 'other')]

describe('buildAgentSpec', () => {
  it('takes the child settings and only the nodes wired to it, without canvas-only fields', () => {
    const spec = buildAgentSpec(canvas[1], canvas, edges)
    expect(spec.child).toEqual({ role: 'Data Analyst', provider: 'openai', model: 'gpt-x', api_key: 'sk',
      system_prompt: 'Write SQL.', allowed_tool_ids: [] })
    expect(spec.tools).toEqual([
      { type: 'tool', data: { label: 'SQL', toolId: 'sql_database', config: { read_only: true } } },
      { type: 'toolkit', data: { label: 'Kit', toolkitId: 'tk', subTools: [{ toolId: 'calculator' }] } },
    ])
    expect(spec.skills).toEqual([{ label: 'Snowflake review', skill_id: 'skill_snowflake_query_review', skill_version: 2 }])
  })
})

describe('instantiateSavedAgent', () => {
  it('recreates the child, its tools and skills, wired to the child', () => {
    const agent: SavedAgent = { id: 'agent_1', name: 'SQL Analyst', icon: '📊', description: '', version: 3,
      updated_at: '', spec: buildAgentSpec(canvas[1], canvas, edges) }
    const { nodes, edges: made } = instantiateSavedAgent(agent, { x: 100, y: 50 }, 'node-9')

    expect(nodes.map((x) => [x.id, x.type])).toEqual([
      ['node-9', 'child_agent'], ['node-9-tool-0', 'tool'], ['node-9-tool-1', 'toolkit'], ['node-9-skill-0', 'skill'],
    ])
    expect(nodes[0].position).toEqual({ x: 100, y: 50 })
    expect(nodes[0].data).toMatchObject({ label: 'SQL Analyst', role: 'Data Analyst', system_prompt: 'Write SQL.',
      saved_agent_id: 'agent_1', saved_agent_version: 3, master_id: '' })
    expect(nodes[1].data).toMatchObject({ toolId: 'sql_database', config: { read_only: true } })
    expect(nodes[3].data).toMatchObject({ skill_id: 'skill_snowflake_query_review', skill_version: 2 })
    expect(made.map((x) => [x.source, x.sourceHandle, x.target, x.targetHandle])).toEqual([
      ['node-9', 'ca-source-bottom', 'node-9-tool-0', 'tool-target-top'],
      ['node-9', 'ca-source-bottom', 'node-9-tool-1', 'tk-target-top'],
      ['node-9', 'ca-source-right', 'node-9-skill-0', 'skill-target-left'],
    ])
  })

  it('round-trips: the dropped agent saves the same spec again', () => {
    const spec = buildAgentSpec(canvas[1], canvas, edges)
    const agent: SavedAgent = { id: 'a', name: 'A', icon: '🤖', description: '', version: 1, updated_at: '', spec }
    const { nodes, edges: made } = instantiateSavedAgent(agent, { x: 0, y: 0 }, 'n')
    const again = buildAgentSpec(nodes[0], nodes, made)
    expect(again.tools).toEqual(spec.tools)
    expect(again.skills.map((s) => s.skill_id)).toEqual(['skill_snowflake_query_review'])
    expect(again.child).toMatchObject(spec.child)
  })
})
