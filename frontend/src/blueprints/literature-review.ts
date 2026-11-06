import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, tool, start, stop } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-literature-review',
  name: 'Literature Review',
  description: 'Searches Semantic Scholar and arXiv, reads the key papers and writes a cited summary of what is known, with evidence strength.',
  badge: 'Research',
  icon: '🎓',
  order: 220,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Literature Reviewer',
        'You are an academic research assistant. Search Semantic Scholar and arXiv with precise terms, pick the most relevant, '
        + 'most cited and most recent work, and read abstracts (and open-access PDFs when available). Summarise what each key '
        + 'paper found, how, and its limits; say whether it is a preprint; note where findings conflict. End with a reference '
        + 'list (authors, year, title, venue, link or DOI). Never invent a paper or DOI.',
        0.3,
      )},
      tool('tool-s2', 340, 520, 'Semantic Scholar', 'semantic_scholar_search', '🎓',
        'Searches 200M+ papers: authors, venues, citation counts, abstracts, open-access PDFs.', { api_key: '', max_results: 5, year: '' }),
      tool('tool-arxiv', 600, 520, 'arXiv Search', 'arxiv_search', '🎓', 'Searches arXiv preprints.', { max_results: 5, sort_by: 'relevance' }),
      stop(700),
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-s2', 'llm-1', 'tool-s2'),
      edge('e-llm-arxiv', 'llm-1', 'tool-arxiv'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
