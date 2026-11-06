import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { child, edge, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-invoice-review',
  name: 'Invoice Capture with Review',
  description: 'An extractor agent reads invoice PDFs into JSON and checks the totals; a person reviews and corrects the fields before they are used.',
  badge: 'Human-in-the-Loop',
  icon: '🧾',
  order: 250,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'master-1', type: 'master_agent', position: { x: 300, y: 250 }, data: {
        label: 'Accounts Payable', provider: 'openai', model: 'gpt-4o', api_key: '',
        goal: 'Extract the invoice the user points to into checked JSON fields.', max_steps: 3, strategy: 'sequential',
      }},
      { id: 'child-extract', type: 'child_agent', position: { x: 600, y: 250 }, data: child(
        'Invoice Extractor', 'Extractor',
        'Read the invoice with the PDF reader. Return JSON only: vendor_name, invoice_number, invoice_date and due_date '
        + '(YYYY-MM-DD), currency, line_items [{description, quantity, unit_price, amount}], subtotal, tax, total, notes. '
        + 'Use null for anything not in the document. Check with the calculator that the line items add up to the subtotal '
        + 'and subtotal + tax to the total; put any difference in notes.',
      )},
      tool('tool-pdf', 900, 160, 'PDF Reader', 'pdf_reader', '📃', 'Extracts the text of a PDF, page by page.',
        { allowed_dir: '', pages: '', max_chars: 20000 }),
      tool('tool-calc', 900, 340, 'Calculator', 'calculator', '🧮', 'Evaluates math expressions.', {}),
      { id: 'gate-1', type: 'human_gate', position: { x: 600, y: 470 }, data: {
        label: 'Review Fields', gate_type: 'edit',
        prompt_message: 'Check the extracted fields against the invoice and correct anything wrong.', timeout_hours: 48, on_timeout: 'reject',
      }},
      stop(300, 520),
    ]
    const edges = [
      edge('e-start-master', 'start-1', 'master-1'),
      edge('e-master-extract', 'master-1', 'child-extract'),
      edge('e-extract-pdf', 'child-extract', 'tool-pdf'),
      edge('e-extract-calc', 'child-extract', 'tool-calc'),
      edge('e-extract-gate', 'child-extract', 'gate-1'),
      edge('e-master-stop', 'master-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
