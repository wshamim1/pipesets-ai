import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, tool, start, stop, slack } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-elt-doctor',
  name: 'Late Data Doctor',
  description: 'Traces stale dashboards back through Fivetran syncs and dbt Cloud runs to the first failing step, then posts the diagnosis to Slack.',
  badge: 'Data',
  icon: '🔧',
  order: 190,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Late Data Doctor',
        'You find why data is late or wrong. Check Fivetran for broken or failing connections and dbt Cloud for errored runs, '
        + 'read the failing step\'s error and trace it upstream (a dbt model failing on a missing column usually follows a broken '
        + 'sync or a schema change). Answer with the first failing step, the root cause, the quoted error, what is affected '
        + 'downstream and the next step. Never trigger, cancel or re-run anything. Post the diagnosis to Slack when asked.',
        0.2,
      )},
      tool('tool-fivetran', 340, 520, 'Fivetran', 'fivetran', '🔵', 'Checks Fivetran connections: sync state, failures, tasks.',
        { api_key: '', api_secret: '', group_id: '', max_results: 50 }),
      tool('tool-dbt', 600, 520, 'dbt Cloud', 'dbt_cloud', '🟧', 'Lists dbt Cloud runs and reads a failed run\'s steps and logs.',
        { base_url: 'https://cloud.getdbt.com', account_id: '', api_token: '', action: 'runs', max_results: 10 }),
      slack('tool-slack', 860, 520, '#data-alerts'),
      stop(700),
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-fivetran', 'llm-1', 'tool-fivetran'),
      edge('e-llm-dbt', 'llm-1', 'tool-dbt'),
      edge('e-llm-slack', 'llm-1', 'tool-slack'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
