/** Node types that call the tools wired to them */
const CALLER_TYPES = new Set(['llm', 'child_agent', 'wf_step'])

/** Footer text for a tool/toolkit card: who calls it, or a hint to wire it up. */
export function callerStatus(neighbours: { type?: string; data: Record<string, unknown> }[]): string {
  const callers = neighbours.filter((n) => CALLER_TYPES.has(n.type ?? ''))
  if (callers.length === 0) return 'Connect to LLM'
  if (callers.length === 1) return `Called by ${String(callers[0].data.label ?? 'LLM')}`
  return `Called by ${callers.length} agents`
}
