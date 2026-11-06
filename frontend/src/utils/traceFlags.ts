import type { TraceRecord } from '../types'

/** A mock / no-key run: answered without calling a model (the backend flags it in metadata). */
export function isSimulated(t: TraceRecord): boolean {
  try {
    return Boolean(t.metadata_json && JSON.parse(t.metadata_json).simulated)
  } catch {
    return false
  }
}

const PHASE_LABELS: Record<string, string> = { middleware: 'Middleware', retrieval: 'Retrieval', embedding: 'Embedding' }

/** How the trace drawer shows a span: model call, tool call, or time spent around them (middleware, RAG). */
export function spanKind(spanType: string): { css: 'llm' | 'tool' | 'phase'; icon: string; label: string } {
  if (spanType === 'llm') return { css: 'llm', icon: '🤖', label: 'LLM' }
  if (spanType in PHASE_LABELS) {
    return { css: 'phase', icon: spanType === 'middleware' ? '🛡' : '📚', label: PHASE_LABELS[spanType] }
  }
  return { css: 'tool', icon: '⚡', label: 'Tool' }
}
