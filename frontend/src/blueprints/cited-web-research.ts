import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { child, edge, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-cited-web-research',
  name: 'Cited Web Research (No Keys)',
  description: 'A researcher agent searches the web and reads the pages that matter; a fact checker verifies every claim against the sources. Runs on free tools.',
  badge: 'Multi-Agent',
  icon: '🌐',
  order: 330,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'master-1', type: 'master_agent', position: { x: 300, y: 250 }, data: {
        label: 'Research Lead', provider: 'openai', model: 'gpt-4o', api_key: '',
        goal: 'Answer the question from the web with every claim checked and cited.', max_steps: 4, strategy: 'sequential',
      }},
      { id: 'child-research', type: 'child_agent', position: { x: 600, y: 120 }, data: child(
        'Web Researcher', 'Web Researcher',
        'Search with 1–3 focused queries, open the 2–4 most relevant pages and read them. Prefer primary, official and recent '
        + 'sources. Answer concisely and list sources as links. Never invent a source or URL.',
      )},
      { id: 'child-check', type: 'child_agent', position: { x: 600, y: 380 }, data: child(
        'Fact Checker', 'Fact Checker',
        'Check each factual claim in the draft against its cited source (re-read the page when needed). Label each SUPPORTED, '
        + 'CONTRADICTED or UNVERIFIED with the evidence, then return the corrected answer with sources.',
      )},
      tool('tool-search', 900, 60, 'DuckDuckGo Search', 'duckduckgo_search', '🦆', 'Free web search.',
        { max_results: 5, region: '', safesearch: 'moderate' }),
      tool('tool-read', 900, 220, 'URL Scraper', 'url_scraper', '🕷️', 'Reads a public web page.', { max_chars: 6000, timeout: 15 }),
      tool('tool-reread', 900, 380, 'URL Scraper', 'url_scraper', '🕷️', 'Re-reads a cited page.', { max_chars: 6000, timeout: 15 }),
      stop(300, 520),
    ]
    const edges = [
      edge('e-start-master', 'start-1', 'master-1'),
      edge('e-master-research', 'master-1', 'child-research'),
      edge('e-master-check', 'master-1', 'child-check'),
      edge('e-research-search', 'child-research', 'tool-search'),
      edge('e-research-read', 'child-research', 'tool-read'),
      edge('e-check-reread', 'child-check', 'tool-reread'),
      edge('e-master-stop', 'master-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
