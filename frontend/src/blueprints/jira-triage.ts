import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-jira-triage',
  name: 'Jira Ticket Triage',
  description: 'Reads Jira issues over MCP, classifies priority and owner, and posts a triage summary to Slack.',
  badge: 'Integrations',
  icon: '🎯',
  order: 70,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Triage Agent',
        'You triage Jira issues. For each issue, read it with the Jira tools, then assign a priority (P0–P3), '
        + 'a likely owning team, and a one-line reason. Post a concise triage summary to Slack when asked.',
        0.3,
      )},
      { id: 'tool-jira', type: 'tool', position: { x: 340, y: 520 }, data: {
        label: 'MCP Jira', toolId: 'mcp_jira', toolType: 'mcp', icon: '🎯',
        description: 'Jira issues, sprints, and projects via the Atlassian MCP server.',
        config: {
          transport: 'stdio', command: 'npx', args: ['-y', '@sooperset/mcp-atlassian'],
          env_vars: { JIRA_URL: '', JIRA_USERNAME: '', JIRA_API_TOKEN: '' },
        },
      }},
      { id: 'tool-slack', type: 'tool', position: { x: 600, y: 520 }, data: {
        label: 'Slack Webhook', toolId: 'slack_webhook', toolType: 'tool', icon: '💬',
        description: 'Posts messages to Slack via an incoming webhook URL.',
        config: { webhook_url: '', channel: '#triage', username: 'Triage Bot' },
      }},
      { id: 'stop-1', type: 'stop', position: { x: 700, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-jira', 'llm-1', 'tool-jira'),
      edge('e-llm-slack', 'llm-1', 'tool-slack'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
