import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, child } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-analyst-panel',
  name: 'Parallel Analyst Panel',
  description: 'Optimist, Skeptic, and Risk analysts evaluate a decision in parallel; the master agent weighs them into one recommendation.',
  badge: 'Multi-Agent',
  icon: '⚖️',
  order: 110,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'master-1', type: 'master_agent', position: { x: 300, y: 250 }, data: {
        label: 'Decision Chair', provider: 'openai', model: 'gpt-4o', api_key: '',
        goal: 'Collect independent analyses of the decision, reconcile disagreements, and give one recommendation with confidence.',
        max_steps: 5, strategy: 'parallel',
      }},
      { id: 'child-optimist', type: 'child_agent', position: { x: 590, y: 90 }, data: child(
        'Optimist Analyst', 'Optimist',
        'Make the strongest honest case FOR the proposal: upside, opportunities, and what has to go right.',
      )},
      { id: 'child-skeptic', type: 'child_agent', position: { x: 590, y: 250 }, data: child(
        'Skeptic Analyst', 'Skeptic',
        'Make the strongest honest case AGAINST the proposal: weak assumptions, missing evidence, and cheaper alternatives.',
      )},
      { id: 'child-risk', type: 'child_agent', position: { x: 590, y: 410 }, data: child(
        'Risk Analyst', 'Risk',
        'List the top risks with likelihood, impact, and a mitigation for each.',
      )},
      { id: 'stop-1', type: 'stop', position: { x: 910, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-master', 'start-1', 'master-1'),
      edge('e-master-optimist', 'master-1', 'child-optimist'),
      edge('e-master-skeptic', 'master-1', 'child-skeptic'),
      edge('e-master-risk', 'master-1', 'child-risk'),
      edge('e-master-stop', 'master-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
