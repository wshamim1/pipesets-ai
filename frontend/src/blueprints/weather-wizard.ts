import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-weather-wizard',
  name: 'Guided Weather Workflow',
  description: 'Step-by-step workflow that asks for a city, looks up the forecast with the Weather tool, and replies — no LLM needed.',
  badge: 'Workflow',
  icon: '🧭',
  order: 120,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 200 }, data: { label: 'Start' } },
      { id: 'step-ask', type: 'wf_step', position: { x: 260, y: 200 }, data: {
        label: 'Ask for city', step_type: 'ask', prompt: 'Which city should I check the weather for?',
        variable: 'city', input_kind: 'text',
      }},
      { id: 'step-lookup', type: 'wf_step', position: { x: 500, y: 200 }, data: {
        label: 'Look up forecast', step_type: 'tool_call', prompt: '', variable: 'forecast',
        tool_id: 'weather', tool_input: '{{city}}',
      }},
      { id: 'tool-weather', type: 'tool', position: { x: 500, y: 380 }, data: {
        label: 'Weather', toolId: 'weather', toolType: 'tool', icon: '🌤️',
        description: 'Gets current weather and forecast for any city.', config: { api_key: '', units: 'metric' },
      }},
      { id: 'step-reply', type: 'wf_step', position: { x: 740, y: 200 }, data: {
        label: 'Reply', step_type: 'message', prompt: 'Here is the weather for {{city}}:\n\n{{forecast}}', variable: '',
      }},
      { id: 'stop-1', type: 'stop', position: { x: 960, y: 200 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-ask', 'start-1', 'step-ask'),
      edge('e-ask-lookup', 'step-ask', 'step-lookup'),
      edge('e-weather-lookup', 'tool-weather', 'step-lookup'),
      edge('e-lookup-reply', 'step-lookup', 'step-reply'),
      edge('e-reply-stop', 'step-reply', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
