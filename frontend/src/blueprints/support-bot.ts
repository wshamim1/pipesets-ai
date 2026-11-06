import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-support-bot',
  name: 'Customer Support Agent',
  description: 'Conversational support LLM with session memory, response cache, and prompt-injection + moderation guardrails.',
  badge: 'Memory & Safety',
  icon: '💬',
  order: 40,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Support Agent',
        'You are a friendly customer support agent. Answer clearly, ask a clarifying question when the request is ambiguous, '
        + 'and never promise refunds or account changes — offer to escalate to a human instead.',
        0.4,
      )},
      { id: 'memory-1', type: 'memory', position: { x: 340, y: 60 }, data: {
        label: 'Session Memory', strategy: 'sliding_window', token_budget: 4000, session_id: 'support-session', session_ttl_hours: 24,
      }},
      { id: 'cache-1', type: 'cache', position: { x: 600, y: 60 }, data: {
        label: 'Response Cache', scope: 'prompt', ttl_seconds: 3600, max_size: 500,
      }},
      { id: 'mw-injection', type: 'middleware', position: { x: 340, y: 520 }, data: {
        label: 'Prompt Injection Guard', middleware_type: 'prompt_injection', config: {}, enabled: true,
      }},
      { id: 'mw-moderation', type: 'middleware', position: { x: 600, y: 520 }, data: {
        label: 'Content Moderation', middleware_type: 'content_moderation', config: {}, enabled: true,
      }},
      { id: 'stop-1', type: 'stop', position: { x: 700, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-memory', 'llm-1', 'memory-1'),
      edge('e-llm-cache', 'llm-1', 'cache-1'),
      edge('e-llm-injection', 'llm-1', 'mw-injection'),
      edge('e-llm-moderation', 'llm-1', 'mw-moderation'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
