import { describe, expect, it } from 'vitest'
import type { ToolCatalogItem } from '../types'
import { agentRoles, agentSystemPrompt, builtinAgentSpec } from './agentCatalog'
import type { AgentCatalog } from './agentCatalog'
import { instantiateSpec } from './savedAgents'
import { agent } from '../test/agentFixtures'

const catalog: AgentCatalog = {
  groups: ['Research & analysis', 'Build your own'], can_edit: true, can_install_tools: true,
  agents: [
    agent({}),
    agent({ id: 'starter_custom', name: 'Custom', role: 'Custom', system_prompt: '', group: 'Build your own' }),
    agent({ id: 'starter_external', name: 'External', role: 'External', kind: 'external', system_prompt: '', group: 'Build your own' }),
  ],
}

describe('agent roles and prompts', () => {
  it('offers the starter roles that run a model, Custom included, not External', () => {
    expect(agentRoles(catalog)).toEqual(['Researcher', 'Custom'])
    expect(agentRoles({ ...catalog, agents: [] })).toEqual(['Custom'])
  })

  it('starts a role with its prompt, or a generic one', () => {
    expect(agentSystemPrompt('Researcher', catalog)).toBe('You research.')
    expect(agentSystemPrompt('Poet', catalog)).toBe('You are a specialist Poet. Complete the task delegated by the master agent.')
  })
})

describe('builtinAgentSpec', () => {
  const tools = new Map<string, ToolCatalogItem>([
    ['sql_database', { id: 'sql_database', name: 'SQL Database', type: 'tool', icon: '🗄️', description: 'Runs SQL',
      default_config: { read_only: true } }],
  ])
  const sql = agent({
    id: 'sql_analyst', name: 'SQL Analyst', role: 'SQL Analyst', starter: false, skills: ['skill_snowflake_query_review'],
    extra: { skill_mode: 'on_demand' },
    tools: [
      { ids: ['snowflake_reader', 'sql_database'], optional: false, why: 'runs queries', installed: 'sql_database', use: 'sql_database' },
      { ids: ['snowflake_catalog'], optional: false, why: 'reads the schema', installed: null, use: 'snowflake_catalog' },
      { ids: ['statistics_tool'], optional: true, why: '', installed: null, use: 'statistics_tool' },
    ],
  })

  it('makes a tool node per need (from the catalog when it has the tool), skipping missing optional ones', () => {
    const spec = builtinAgentSpec(sql, tools)
    expect(spec.child).toEqual({ role: 'SQL Analyst', system_prompt: 'You research.', kind: 'llm', skill_mode: 'on_demand' })
    expect(spec.tools.map((t) => t.data.toolId)).toEqual(['sql_database', 'snowflake_catalog'])
    expect(spec.tools[0].data).toMatchObject({ label: 'SQL Database', toolType: 'tool', config: { read_only: true } })
    expect(spec.tools[1].data).toMatchObject({ label: 'snowflake_catalog', config: {} })
    expect(spec.skills).toEqual([{ skill_id: 'skill_snowflake_query_review', label: 'skill_snowflake_query_review' }])
  })

  it('makes one tool node when two needs use the same tool', () => {
    const triage = agent({ starter: false, tools: [
      { ids: ['github_api', 'jira'], optional: false, why: '', installed: 'jira', use: 'jira' },
      { ids: ['jira', 'linear'], optional: true, why: '', installed: 'jira', use: 'jira' },
    ] })
    expect(builtinAgentSpec(triage, tools).tools.map((t) => t.data.toolId)).toEqual(['jira'])
  })

  it('drops as a child wired to its tools and skills, recording where it came from', () => {
    const { nodes, edges } = instantiateSpec(builtinAgentSpec(sql, tools), { x: 0, y: 0 }, 'n',
      { label: 'SQL Analyst Agent', builtin_agent_id: 'sql_analyst' })
    expect(nodes[0].data).toMatchObject({ label: 'SQL Analyst Agent', builtin_agent_id: 'sql_analyst', role: 'SQL Analyst' })
    expect(nodes.map((x) => x.type)).toEqual(['child_agent', 'tool', 'tool', 'skill'])
    expect(edges).toHaveLength(3)
  })
})
