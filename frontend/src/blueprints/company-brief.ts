import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-company-brief',
  name: 'Public Company Brief',
  description: 'Builds a sourced brief on a listed company from its latest SEC filings, share price and this week\'s news — research, not investment advice.',
  badge: 'Research',
  icon: '🏢',
  order: 280,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Company Analyst',
        'You write factual company briefs. Identify the company and ticker, read its latest 10-K / 10-Q / 8-K filings, get the '
        + 'share price and recent change, and search this week\'s news from credible outlets. Write: what the company does, latest '
        + 'results, notable events and risks, what changed recently — every fact with its source link and date. Never recommend '
        + 'buying or selling.',
        0.3,
      )},
      tool('tool-sec', 340, 520, 'SEC EDGAR Filings', 'sec_edgar_filings', '🏛️', 'A US public company\'s latest SEC filings.',
        { user_agent: '', form_type: '', max_results: 10 }),
      tool('tool-quote', 600, 520, 'Stock Quote', 'stock_quote', '💹', 'Latest price and change (may be delayed).', { range: '5d' }),
      tool('tool-news', 860, 520, 'News Search', 'news_search', '🗞️', 'Latest news from Google News.',
        { max_results: 8, language: 'en', country: 'US', time_range: '7d' }),
      stop(700),
    ]
    const edges = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-sec', 'llm-1', 'tool-sec'),
      edge('e-llm-quote', 'llm-1', 'tool-quote'),
      edge('e-llm-news', 'llm-1', 'tool-news'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
