import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, tool, start, stop } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-airflow-oncall',
  name: 'Airflow On-Call (Skill)',
  description: 'An on-call LLM that loads the Airflow DAG triage skill only when a question needs it, then reads runs, task logs and import errors.',
  badge: 'Skills',
  icon: '🌬️',
  order: 180,
  build() {
    const airflow = { base_url: 'http://localhost:8080', api_version: 'v1', username: '', password: '', api_token: '' }
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: {
        ...llm('On-Call Assistant',
          'You are the data platform on-call assistant. Load a skill when a question matches it, then work from the evidence your tools return.',
          0.2),
        skill_mode: 'on_demand',
      }},
      { id: 'skill-1', type: 'skill', position: { x: 340, y: 60 }, data: {
        label: 'Airflow DAG triage', skill_id: 'skill_airflow_triage', icon: '🌬️',
        description: 'When the user asks why an Airflow DAG run failed, is stuck or didn\'t start.', instructions: '',
        category: 'data-platform', tool_ids: ['airflow', 'airflow_task_logs', 'airflow_import_errors', 'airflow_health'],
        tags: ['airflow', 'on-call', 'triage'],
      }},
      tool('tool-airflow', 340, 520, 'Apache Airflow', 'airflow', '🌬️', 'Lists DAGs, recent runs and task states.',
        { ...airflow, action: 'list_dags', allow_trigger: false, max_results: 10 }),
      tool('tool-logs', 600, 520, 'Airflow Task Logs', 'airflow_task_logs', '📜', 'Reads the end of a task\'s log.',
        { ...airflow, max_chars: 6000 }),
      tool('tool-imports', 860, 520, 'Airflow Import Errors', 'airflow_import_errors', '🧩', 'Lists DAG files that failed to import.',
        { ...airflow, max_results: 10 }),
      tool('tool-health', 1120, 520, 'Airflow Health', 'airflow_health', '🩺', 'Checks the scheduler, metadatabase and triggerer.', airflow),
      stop(700),
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-skill-llm', 'skill-1', 'llm-1'),
      edge('e-llm-airflow', 'llm-1', 'tool-airflow'),
      edge('e-llm-logs', 'llm-1', 'tool-logs'),
      edge('e-llm-imports', 'llm-1', 'tool-imports'),
      edge('e-llm-health', 'llm-1', 'tool-health'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
