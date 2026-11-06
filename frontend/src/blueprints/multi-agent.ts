import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-multi-agent',
  name: 'Multi-Agent Research Crew',
  description: 'Master Agent coordinating specialized Researcher, Writer, and Reviewer child agents.',
  badge: 'Multi-Agent',
  icon: '🤖',
  order: 20,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'master-1', type: 'master_agent', position: { x: 300, y: 250 }, data: {
        label: 'Master Agent', provider: 'openai', model: 'gpt-4o', api_key: '',
        goal: 'Coordinate child agents to produce a high-quality final answer.',
        max_steps: 5, strategy: 'sequential',
      }},
      { id: 'child-research', type: 'child_agent', position: { x: 590, y: 90 }, data: {
        label: 'Researcher Agent', master_id: 'master-1', role: 'Researcher',
        provider: 'openai', model: 'gpt-4o', api_key: '', allowed_tool_ids: [],
        system_prompt: 'Research the topic thoroughly and gather accurate references.',
      }},
      { id: 'child-writer', type: 'child_agent', position: { x: 590, y: 250 }, data: {
        label: 'Writer Agent', master_id: 'master-1', role: 'Writer',
        provider: 'openai', model: 'gpt-4o', api_key: '', allowed_tool_ids: [],
        system_prompt: 'Draft a clear and concise response from the research notes.',
      }},
      { id: 'child-reviewer', type: 'child_agent', position: { x: 590, y: 410 }, data: {
        label: 'Reviewer Agent', master_id: 'master-1', role: 'Reviewer',
        provider: 'openai', model: 'gpt-4o', api_key: '', allowed_tool_ids: [],
        system_prompt: 'Review for factual accuracy, clarity, and completeness.',
      }},
      { id: 'stop-1', type: 'stop', position: { x: 910, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-master', 'start-1', 'master-1'),
      edge('e-master-research', 'master-1', 'child-research'),
      edge('e-master-writer', 'master-1', 'child-writer'),
      edge('e-master-reviewer', 'master-1', 'child-reviewer'),
      edge('e-master-stop', 'master-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
