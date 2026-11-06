import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, child } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-content-studio',
  name: 'Content Studio with Approval',
  description: 'Researcher, Writer, and Editor agents draft an article; a human approval gate signs off before it is exported to PDF.',
  badge: 'Human-in-the-Loop',
  icon: '✍️',
  order: 80,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'master-1', type: 'master_agent', position: { x: 300, y: 250 }, data: {
        label: 'Editor-in-Chief', provider: 'openai', model: 'gpt-4o', api_key: '',
        goal: 'Produce a well-researched, publication-ready article on the requested topic.',
        max_steps: 6, strategy: 'sequential',
      }},
      { id: 'child-research', type: 'child_agent', position: { x: 590, y: 70 }, data: child(
        'Researcher Agent', 'Researcher',
        'Search the web for current, credible sources on the topic. Return key facts with their source URLs.',
        ['tool-web'],
      )},
      { id: 'child-writer', type: 'child_agent', position: { x: 590, y: 250 }, data: child(
        'Writer Agent', 'Writer',
        'Write an engaging 600–800 word article from the research notes, with a headline and short sections.',
      )},
      { id: 'child-editor', type: 'child_agent', position: { x: 590, y: 430 }, data: child(
        'Editor Agent', 'Editor',
        'Tighten the draft, fix factual or tone issues, and export the final version to PDF.',
        ['tool-pdf'],
      )},
      { id: 'tool-web', type: 'tool', position: { x: 880, y: 70 }, data: {
        label: 'DuckDuckGo Search', toolId: 'duckduckgo_search', toolType: 'tool', icon: '🦆',
        description: 'Searches real-time web information and answers.', config: { api_key: '', max_results: 5 },
      }},
      { id: 'tool-pdf', type: 'tool', position: { x: 880, y: 430 }, data: {
        label: 'PDF Generator', toolId: 'pdf_generator', toolType: 'tool', icon: '🧾',
        description: 'Generates a PDF document from input text.',
        config: { output_dir: '', file_name: '', title: '', page_size: 'A4' },
      }},
      { id: 'gate-1', type: 'human_gate', position: { x: 300, y: 470 }, data: {
        label: 'Publish Approval', gate_type: 'approval',
        prompt_message: 'Review the final article before it is exported.', timeout_hours: 24, on_timeout: 'reject',
      }},
      { id: 'stop-1', type: 'stop', position: { x: 300, y: 620 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-master', 'start-1', 'master-1'),
      edge('e-master-research', 'master-1', 'child-research'),
      edge('e-master-writer', 'master-1', 'child-writer'),
      edge('e-master-editor', 'master-1', 'child-editor'),
      edge('e-research-web', 'child-research', 'tool-web'),
      edge('e-editor-pdf', 'child-editor', 'tool-pdf'),
      edge('e-master-gate', 'master-1', 'gate-1'),
      edge('e-gate-stop', 'gate-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
