/** A JSON-schema object of a tool's parameters, as the backend sends it (catalog, signature, MCP discovery). */
export interface ParamSchema {
  properties?: Record<string, { type?: string; description?: string; enum?: unknown[]; default?: unknown }>
  required?: string[]
}

/** One readable line per parameter: "city: string (required) — City name", "units: metric | imperial = "metric"". */
export function describeParams(schema?: ParamSchema | null): string[] {
  const required = new Set(schema?.required ?? [])
  return Object.entries(schema?.properties ?? {}).map(([name, p]) => {
    const type = p.enum ? p.enum.map(String).join(' | ') : p.type ?? 'any'
    const extra = required.has(name) ? ' (required)' : p.default !== undefined ? ` = ${JSON.stringify(p.default)}` : ''
    return `${name}: ${type}${extra}${p.description ? ` — ${p.description}` : ''}`
  })
}
