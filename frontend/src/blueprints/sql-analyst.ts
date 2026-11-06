import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-sql-analyst',
  name: 'SQL Data Analyst',
  description: 'Answers business questions by querying a read-only SQL database and running Python for charts and stats.',
  badge: 'Data',
  icon: '🗄️',
  order: 50,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Data Analyst',
        'You are a data analyst. Inspect the schema before writing SQL, only run read-only queries, and show the query you ran. '
        + 'Use Python for calculations or charts, then summarise the findings in plain language.',
        0.2,
      )},
      { id: 'tool-sql', type: 'tool', position: { x: 340, y: 520 }, data: {
        label: 'Postgres / SQL Database', toolId: 'sql_database', toolType: 'tool', icon: '🗄️',
        description: 'Queries tables and extracts structured enterprise data.',
        config: { connection_string: '', read_only: true },
      }},
      { id: 'tool-python', type: 'tool', position: { x: 600, y: 520 }, data: {
        label: 'Python Sandbox', toolId: 'python_interpreter', toolType: 'tool', icon: '🐍',
        description: 'Executes Python scripts in an isolated sandbox.',
        config: { timeout: 10, backend: 'auto', memory_mb: 256, allow_network: false, image: 'python:3.12-slim' },
      }},
      { id: 'stop-1', type: 'stop', position: { x: 700, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-sql', 'llm-1', 'tool-sql'),
      edge('e-llm-python', 'llm-1', 'tool-python'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
