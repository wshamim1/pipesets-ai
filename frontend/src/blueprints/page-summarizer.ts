import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-page-summarizer',
  name: 'Web Page Summarizer',
  description: 'Scrapes any public URL and returns a TL;DR, key points, and notable quotes; can email the digest via SMTP.',
  badge: 'Tools & MCP',
  icon: '🕷️',
  order: 150,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Page Summarizer',
        'Scrape the URL the user gives you, then return: a one-line TL;DR, 5 key points, and up to 3 notable quotes. '
        + 'Only email the digest when the user explicitly asks.',
        0.3,
      )},
      { id: 'tool-scraper', type: 'tool', position: { x: 340, y: 520 }, data: {
        label: 'URL Scraper', toolId: 'url_scraper', toolType: 'tool', icon: '🕷️',
        description: 'Fetches and extracts readable text from any public URL.', config: { max_chars: 8000, timeout: 15 },
      }},
      { id: 'tool-email', type: 'tool', position: { x: 600, y: 520 }, data: {
        label: 'Email Sender (SMTP)', toolId: 'email_sender', toolType: 'tool', icon: '📧',
        description: 'Sends emails via SMTP. Input is the message body.',
        config: {
          smtp_host: 'smtp.gmail.com', smtp_port: 587, username: '', password: '',
          from_address: '', to_address: '', subject: 'Page digest',
        },
      }},
      { id: 'stop-1', type: 'stop', position: { x: 700, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-scraper', 'llm-1', 'tool-scraper'),
      edge('e-llm-email', 'llm-1', 'tool-email'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
