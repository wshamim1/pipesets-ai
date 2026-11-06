import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-tool-agent',
  name: 'Tool-Equipped Assistant',
  description: 'GPT-4O connected to Live Weather, Tavily Web Search, and File Reader tools.',
  badge: 'Tools & MCP',
  icon: '🛠️',
  order: 30,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 320, y: 300 }, data: {
        label: 'Tool-Enabled LLM', provider: 'openai', model: 'gpt-4o',
        temperature: 0.7, max_tokens: 1024, top_p: 1.0, api_key: '',
        system_prompt: 'Use connected tools when useful, then provide a concise answer.', base_url: '',
      }},
      { id: 'tool-web', type: 'tool', position: { x: 320, y: 520 }, data: {
        label: 'DuckDuckGo Search', toolId: 'duckduckgo_search', toolType: 'tool', icon: '🦆',
        description: 'Searches real-time web information and answers.', config: { api_key: '', max_results: 5 },
      }},
      { id: 'tool-file', type: 'tool', position: { x: 580, y: 520 }, data: {
        label: 'File Reader', toolId: 'file_reader', toolType: 'tool', icon: '📄',
        description: 'Reads local text/code files. Input is the file path.', config: { allowed_dir: '', max_bytes: 32768 },
      }},
      { id: 'tool-calc', type: 'tool', position: { x: 840, y: 520 }, data: {
        label: 'Calculator', toolId: 'calculator', toolType: 'tool', icon: '🧮',
        description: 'Evaluates safe math expressions.', config: {},
      }},
      { id: 'stop-1', type: 'stop', position: { x: 680, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-tool-web', 'llm-1', 'tool-web'),
      edge('e-llm-tool-file', 'llm-1', 'tool-file'),
      edge('e-llm-tool-calc', 'llm-1', 'tool-calc'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
