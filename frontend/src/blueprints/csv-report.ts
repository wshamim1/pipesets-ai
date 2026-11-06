import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-csv-report',
  name: 'CSV Report Builder',
  description: 'Reads a CSV, analyses it in the Python sandbox, and writes the findings up as a downloadable PDF report.',
  badge: 'Data',
  icon: '📊',
  order: 140,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Report Analyst',
        'Load the CSV the user names, profile it (rows, columns, missing values), compute the requested metrics in Python, '
        + 'then write a short report with findings and recommendations and save it as a PDF.',
        0.3,
      )},
      { id: 'tool-csv', type: 'tool', position: { x: 340, y: 520 }, data: {
        label: 'CSV Reader', toolId: 'csv_reader', toolType: 'tool', icon: '📊',
        description: 'Reads a local CSV file and returns its contents as a markdown table.', config: { allowed_dir: '', max_rows: 50 },
      }},
      { id: 'tool-python', type: 'tool', position: { x: 600, y: 520 }, data: {
        label: 'Python Sandbox', toolId: 'python_interpreter', toolType: 'tool', icon: '🐍',
        description: 'Executes Python scripts in an isolated sandbox.',
        config: { timeout: 10, backend: 'auto', memory_mb: 256, allow_network: false, image: 'python:3.12-slim' },
      }},
      { id: 'tool-pdf', type: 'tool', position: { x: 860, y: 520 }, data: {
        label: 'PDF Generator', toolId: 'pdf_generator', toolType: 'tool', icon: '🧾',
        description: 'Generates a PDF document from input text.',
        config: { output_dir: '', file_name: 'report.pdf', title: 'Data Report', page_size: 'A4' },
      }},
      { id: 'stop-1', type: 'stop', position: { x: 700, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-csv', 'llm-1', 'tool-csv'),
      edge('e-llm-python', 'llm-1', 'tool-python'),
      edge('e-llm-pdf', 'llm-1', 'tool-pdf'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
