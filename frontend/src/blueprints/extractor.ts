import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-extractor',
  name: 'Structured Data Extractor',
  description: 'Low-temperature LLM with a strict JSON output parser that turns invoices, emails, or notes into typed fields.',
  badge: 'Structured Output',
  icon: '🧾',
  order: 60,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Extraction LLM',
        'Extract the requested fields from the user\'s document. Use null for anything not present — never guess. '
        + 'Return only JSON matching the schema.',
        0,
      )},
      { id: 'parser-1', type: 'output_parser', position: { x: 340, y: 60 }, data: {
        label: 'Invoice JSON Parser', parser_type: 'json', strict: true,
        schema_json: JSON.stringify({
          vendor: { type: 'string' },
          invoice_number: { type: 'string' },
          invoice_date: { type: 'string' },
          total: { type: 'number' },
          currency: { type: 'string' },
          line_items: { type: 'array' },
        }, null, 2),
      }},
      { id: 'stop-1', type: 'stop', position: { x: 700, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-parser', 'llm-1', 'parser-1'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
