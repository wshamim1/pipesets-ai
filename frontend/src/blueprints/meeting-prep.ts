import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-meeting-prep',
  name: 'Meeting Prep Briefs',
  description: 'Reads today\'s meetings, finds your recent email threads with each attendee, looks up external companies, and writes a short brief per meeting.',
  badge: 'Productivity',
  icon: '🗓️',
  order: 320,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Meeting Prep',
        'You prepare meeting briefs. Read the calendar for the meetings asked about (default: the rest of today). For each, find '
        + 'recent email threads with its attendees and note open questions and commitments; look up external attendees\' companies '
        + 'briefly on the web. Write one brief per meeting under 150 words: time, purpose, who\'s coming, context, open items and '
        + '2–3 talking points. Never accept, decline or move events, or send email.',
        0.3,
      )},
      tool('tool-cal', 340, 520, 'Google Calendar', 'google_calendar', '🗓️', 'Reads calendar events.', { calendar_id: 'primary', access_token: '' }),
      tool('tool-gmail', 600, 520, 'Gmail', 'gmail_reader', '📬', 'Searches and reads Gmail messages.',
        { access_token: '', query: 'newer_than:30d', max_results: 10, max_chars: 4000 }),
      tool('tool-web', 860, 520, 'DuckDuckGo Search', 'duckduckgo_search', '🦆', 'Free web search.',
        { max_results: 5, region: '', safesearch: 'moderate' }),
      stop(700),
    ]
    const edges = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-cal', 'llm-1', 'tool-cal'),
      edge('e-llm-gmail', 'llm-1', 'tool-gmail'),
      edge('e-llm-web', 'llm-1', 'tool-web'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
