import type { BuiltinAgent } from '../utils/agentCatalog'

/** A built-in agent as GET /api/agent-catalog returns it (a starter Researcher unless overridden). */
export const agent = (fields: Partial<BuiltinAgent>): BuiltinAgent => ({
  id: 'starter_researcher', name: 'Researcher', icon: '🔍', group: 'Research & analysis', description: 'Finds things.',
  role: 'Researcher', system_prompt: 'You research.', kind: 'llm', starter: true, tools: [], skills: [], is_new: false,
  extra: {}, eval_cases: 0, ready: true, missing_tools: [], installed: true, source: 'default', in_use: false, ...fields,
})
