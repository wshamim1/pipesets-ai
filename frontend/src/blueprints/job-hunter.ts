import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, tool, start, stop } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-job-hunter',
  name: 'Job Hunter',
  description: 'Searches LinkedIn, Indeed and Naukri listings via Google Jobs plus companies\' own careers boards, then ranks roles against your profile with apply links.',
  badge: 'Jobs & Careers',
  icon: '💼',
  order: 160,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Job Search Assistant',
        'You help a candidate find jobs that fit them. From their message, work out the role, location or remote, seniority, '
        + 'key skills and salary floor. Search Google Jobs (it lists postings from LinkedIn, Indeed, Naukri and company sites) '
        + 'and, for companies they name, read the company\'s own careers board. Merge duplicates (keep every apply link), drop '
        + 'off-target roles, and return the top matches as a table: role, company, location, salary if listed, posted, why it '
        + 'fits, apply links. Never apply for the candidate and never invent a posting or link.',
        0.3,
      )},
      tool('tool-gjobs', 340, 520, 'Google Jobs', 'google_jobs', '💼',
        'Searches job listings across LinkedIn, Indeed, Naukri, Glassdoor and company sites via Google Jobs (SerpApi).',
        { api_key: '', location: '', gl: '', hl: 'en', max_results: 10 }),
      tool('tool-company', 600, 520, 'Company Jobs', 'company_jobs', '🏢',
        'Lists a company\'s open roles from its Greenhouse, Lever or Ashby careers board.',
        { filter: '', lever_region: 'global', max_results: 30 }),
      stop(700),
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-gjobs', 'llm-1', 'tool-gjobs'),
      edge('e-llm-company', 'llm-1', 'tool-company'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
