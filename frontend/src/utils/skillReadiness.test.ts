import { describe, expect, it } from 'vitest'
import type { FlowEdge, FlowNode } from '../types'
import { describeSkillIssue, skillReadiness } from './skillReadiness'
import { validatePipeline } from './pipelineValidation'

const n = (id: string, type: string, data: Record<string, unknown>) => ({ id, type, position: { x: 0, y: 0 }, data }) as unknown as FlowNode
const e = (source: string, target: string) => ({ id: `${source}-${target}`, source, target }) as FlowEdge
const required = (t: string) => (t.startsWith('airflow') ? ['base_url'] : [])

const base = [
  n('llm', 'llm', { label: 'LLM', provider: 'mock', model: 'm' }),
  n('sk', 'skill', { label: 'Airflow triage', skill_id: 'skill_airflow_triage', requiredTools: ['airflow', 'airflow_task_logs'] }),
  n('t1', 'tool', { label: 'Airflow', toolId: 'airflow', config: { base_url: '' } }),
]
const edges = [e('llm', 'sk'), e('llm', 't1')]

describe('skillReadiness', () => {
  it('lists tools to attach and settings to fill', () => {
    const [issue] = skillReadiness(base, edges, required)
    expect(issue.missingTools).toEqual(['airflow_task_logs'])
    expect(issue.unconfigured).toEqual([{ nodeId: 't1', label: 'Airflow', keys: ['base_url'] }])
    expect(describeSkillIssue(issue)).toBe('attach airflow_task_logs; set base_url on Airflow')
  })

  it('is ready once everything is attached and set; a linked connection counts as set', () => {
    const nodes = [...base.slice(0, 2),
      n('t1', 'tool', { label: 'Airflow', toolId: 'airflow', config: { base_url: 'http://af' } }),
      n('t2', 'tool', { label: 'Logs', toolId: 'airflow_task_logs', config: {} }),
      n('c', 'connection', {})]
    expect(skillReadiness(nodes, [...edges, e('llm', 't2'), e('t2', 'c')], required)).toEqual([])
  })

  it('falls back to the node’s own tool list, and ignores skills not wired to an LLM', () => {
    const legacy = [base[0], n('sk', 'skill', { label: 'Legacy', tool_ids: ['calculator'] })]
    expect(skillReadiness(legacy, [e('llm', 'sk')], required)[0].missingTools).toEqual(['calculator'])
    expect(skillReadiness(legacy, [], required)).toEqual([])
  })

  it('is a blocking validation error on the skill node', () => {
    const issues = validatePipeline(base, edges, () => 'key', required).filter((i) => i.id.startsWith('skill-not-ready'))
    expect(issues).toEqual([expect.objectContaining({ severity: 'error', nodeId: 'sk', title: 'Skill “Airflow triage” isn\'t ready' })])
  })
})
