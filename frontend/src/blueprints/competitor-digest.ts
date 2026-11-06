import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, child, tool, start, stop } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-competitor-digest',
  name: 'Competitor News Digest',
  description: 'A News Monitor and a Writer agent turn this week\'s coverage of your competitors into a short email digest with sources.',
  badge: 'Multi-Agent',
  icon: '📰',
  order: 210,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'master-1', type: 'master_agent', position: { x: 300, y: 250 }, data: {
        label: 'Digest Editor', provider: 'openai', model: 'gpt-4o', api_key: '',
        goal: 'Produce this week\'s competitor digest from the companies the user names, and email it.',
        max_steps: 4, strategy: 'sequential',
      }},
      { id: 'child-news', type: 'child_agent', position: { x: 600, y: 120 }, data: child(
        'News Monitor', 'News Monitor',
        'Search the last 7 days of news for each company named. Drop duplicates and press-release rewrites; keep 3–8 items '
        + 'per company with outlet, date and link. Never invent a story.',
      )},
      { id: 'child-writer', type: 'child_agent', position: { x: 600, y: 380 }, data: child(
        'Digest Writer', 'Writer',
        'Turn the news items into a short digest: a headline per company, two lines on why each item matters, sources as links. '
        + 'Email it when done.',
      )},
      tool('tool-news', 900, 60, 'News Search', 'news_search', '🗞️', 'Latest news on a topic from Google News (no key).',
        { max_results: 8, language: 'en', country: 'US', time_range: '7d' }),
      tool('tool-scraper', 900, 200, 'URL Scraper', 'url_scraper', '🕷️', 'Reads a public web page.', { max_chars: 4000, timeout: 15 }),
      tool('tool-email', 900, 380, 'Email Sender', 'email_sender', '📧', 'Sends emails via SMTP.', {
        smtp_host: 'smtp.gmail.com', smtp_port: 587, username: '', password: '', from_address: '', to_address: '',
        subject: 'Weekly competitor digest',
      }),
      stop(300, 520),
    ]
    const edges: FlowEdge[] = [
      edge('e-start-master', 'start-1', 'master-1'),
      edge('e-master-news', 'master-1', 'child-news'),
      edge('e-master-writer', 'master-1', 'child-writer'),
      edge('e-news-search', 'child-news', 'tool-news'),
      edge('e-news-scraper', 'child-news', 'tool-scraper'),
      edge('e-writer-email', 'child-writer', 'tool-email'),
      edge('e-master-stop', 'master-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
