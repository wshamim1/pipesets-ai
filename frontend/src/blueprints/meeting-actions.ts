import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-meeting-actions',
  name: 'Meeting Notes → Action Items',
  description: 'Turns raw meeting notes into owners, due dates, and decisions as strict JSON, then posts the summary to Slack.',
  badge: 'Structured Output',
  icon: '📝',
  order: 130,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Meeting Summarizer',
        'Read the meeting notes and extract decisions, action items (owner, task, due date), and open questions. '
        + 'Use null when an owner or date is not stated. If asked, post a short summary to Slack.',
        0,
      )},
      { id: 'parser-1', type: 'output_parser', position: { x: 340, y: 60 }, data: {
        label: 'Action Items JSON', parser_type: 'json', strict: true,
        schema_json: JSON.stringify({
          summary: { type: 'string' },
          decisions: { type: 'array' },
          action_items: { type: 'array' },
          open_questions: { type: 'array' },
        }, null, 2),
      }},
      { id: 'tool-slack', type: 'tool', position: { x: 340, y: 520 }, data: {
        label: 'Slack Webhook', toolId: 'slack_webhook', toolType: 'tool', icon: '💬',
        description: 'Posts messages to Slack via an incoming webhook URL.',
        config: { webhook_url: '', channel: '#team', username: 'Meeting Bot' },
      }},
      { id: 'stop-1', type: 'stop', position: { x: 700, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-parser', 'llm-1', 'parser-1'),
      edge('e-llm-slack', 'llm-1', 'tool-slack'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
