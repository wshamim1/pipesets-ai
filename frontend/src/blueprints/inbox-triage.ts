import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-inbox-triage',
  name: 'Inbox Triage',
  description: 'Sorts your Gmail into needs-you-today, this week, FYI and ignore, flags phishing, and drafts replies — checking your calendar before proposing times.',
  badge: 'Productivity',
  icon: '📥',
  order: 260,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Inbox Triage',
        'You triage an email inbox. List unread messages from the last 2 days (or what the user asks for) and read the ones whose '
        + 'subject isn\'t enough. Sort them into Needs you today, This week, FYI and Ignore. For each Needs-you item give sender, '
        + 'the ask in one line and the deadline, and draft a short reply when one is needed; check the calendar before proposing '
        + 'meeting times. Flag likely phishing (urgent payments, credential requests, lookalike domains). Never send anything.',
        0.3,
      )},
      tool('tool-gmail', 340, 520, 'Gmail', 'gmail_reader', '📬', 'Searches and reads Gmail messages.',
        { access_token: '', query: 'is:unread newer_than:2d', max_results: 25, max_chars: 5000 }),
      tool('tool-cal', 600, 520, 'Google Calendar', 'google_calendar', '🗓️', 'Reads calendar events.', { calendar_id: 'primary', access_token: '' }),
      stop(700),
    ]
    const edges = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-gmail', 'llm-1', 'tool-gmail'),
      edge('e-llm-cal', 'llm-1', 'tool-cal'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
