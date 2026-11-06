import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { child, edge, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-zendesk-support',
  name: 'Zendesk Reply Drafter',
  description: 'A support agent reads the Zendesk ticket and its history, finds the answer in Confluence, and drafts a reply an agent approves or edits.',
  badge: 'Integrations',
  icon: '🎧',
  order: 270,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'master-1', type: 'master_agent', position: { x: 300, y: 250 }, data: {
        label: 'Support Lead', provider: 'openai', model: 'gpt-4o', api_key: '',
        goal: 'Draft an accurate, friendly reply to the ticket the user names.', max_steps: 3, strategy: 'sequential',
      }},
      { id: 'child-support', type: 'child_agent', position: { x: 600, y: 250 }, data: child(
        'Support Desk Agent', 'Support Desk Agent',
        'Read the ticket and its conversation. Find the answer in the help docs and link the article you used; never invent '
        + 'policies, prices or refunds. Draft a short reply in the customer\'s language. Recommend escalating to a human for '
        + 'refunds, security or legal issues, or when the docs don\'t cover it. Return: summary, suggested tags and priority, draft.',
      )},
      tool('tool-zendesk', 900, 160, 'Zendesk', 'zendesk', '🎧', 'Searches and reads Zendesk tickets.',
        { subdomain: '', email: '', api_token: '', action: 'auto', priority: 'normal', max_results: 10 }),
      tool('tool-confluence', 900, 340, 'Confluence', 'confluence', '🗒️', 'Searches and reads Confluence pages.',
        { base_url: '', email: '', api_token: '', action: 'auto', space_key: '', max_results: 5, max_chars: 8000 }),
      { id: 'gate-1', type: 'human_gate', position: { x: 600, y: 470 }, data: {
        label: 'Approve Reply', gate_type: 'edit',
        prompt_message: 'Read the draft, edit it if needed, and approve it before it goes to the customer.', timeout_hours: 8, on_timeout: 'reject',
      }},
      stop(300, 520),
    ]
    const edges = [
      edge('e-start-master', 'start-1', 'master-1'),
      edge('e-master-support', 'master-1', 'child-support'),
      edge('e-support-zendesk', 'child-support', 'tool-zendesk'),
      edge('e-support-confluence', 'child-support', 'tool-confluence'),
      edge('e-support-gate', 'child-support', 'gate-1'),
      edge('e-master-stop', 'master-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
