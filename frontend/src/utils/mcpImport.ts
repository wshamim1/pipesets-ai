/**
 * Reads the MCP server config people copy from READMEs — Claude Desktop / Cursor / AWS
 * (`{"mcpServers": {...}}`), VS Code (`{"servers": {...}}`), a bare `{"name": {...}}` map or a
 * single server object — into the fields of the Add Custom MCP Server form.
 */

export interface ImportedMcpServer {
  name: string
  transport: 'stdio' | 'sse' | 'http'
  command: string
  args: string[]
  env_vars: Record<string, string>
  url: string
  headers: Record<string, string>
}

export interface McpImportResult {
  server: ImportedMcpServer
  /** Other servers in the paste, by name; the form adds one server at a time */
  others: string[]
  /** Keys we can't use (timeout, cwd, autoApprove, …), so the user knows they were dropped */
  ignored: string[]
}

// What the form fills; `type` / `transport` pick the transport
const USED = new Set(['command', 'args', 'env', 'url', 'serverUrl', 'httpUrl', 'headers', 'type', 'transport'])

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const isServer = (v: unknown): v is Record<string, unknown> =>
  isObject(v) && ['command', 'url', 'serverUrl', 'httpUrl'].some((k) => typeof v[k] === 'string')

function strings(v: unknown, what: string): Record<string, string> {
  if (v === undefined || v === null) return {}
  if (!isObject(v)) throw new Error(`"${what}" must be an object`)
  return Object.fromEntries(Object.entries(v).map(([k, val]) => [k, String(val)]))
}

function transportOf(s: Record<string, unknown>): ImportedMcpServer['transport'] {
  const t = String(s.type ?? s.transport ?? '').toLowerCase().replace(/[-_]/g, '')
  if (t === 'sse') return 'sse'
  if (t === 'stdio') return 'stdio'
  if (t === 'http' || t === 'streamablehttp') return 'http'
  if (t) throw new Error(`Unknown transport "${String(s.type ?? s.transport)}" (use stdio, http or sse)`)
  return typeof s.command === 'string' ? 'stdio' : 'http'
}

export function parseMcpConfig(text: string): McpImportResult {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch (e) {
    throw new Error(`Not valid JSON: ${(e as Error).message}`)
  }
  if (!isObject(raw)) throw new Error('Expected a JSON object')

  // Unwrap {"mcpServers": {...}} / {"servers": {...}}, or take a single server object as is
  const map = isObject(raw.mcpServers) ? raw.mcpServers : isObject(raw.servers) ? raw.servers : raw
  const entries: [string, Record<string, unknown>][] = isServer(map)
    ? [['', map]]
    : Object.entries(map).filter((e): e is [string, Record<string, unknown>] => isServer(e[1]))
  if (!entries.length) throw new Error('No MCP server found — expected "command" (stdio) or "url" (HTTP / SSE)')

  const [name, s] = entries[0]
  const transport = transportOf(s)
  if (s.args !== undefined && !Array.isArray(s.args)) throw new Error('"args" must be a list')
  return {
    server: {
      name,
      transport,
      command: typeof s.command === 'string' ? s.command : '',
      args: ((s.args as unknown[]) ?? []).map(String),
      env_vars: strings(s.env, 'env'),
      url: String(s.url ?? s.serverUrl ?? s.httpUrl ?? ''),
      headers: strings(s.headers, 'headers'),
    },
    others: entries.slice(1).map(([n]) => n),
    ignored: Object.keys(s).filter((k) => !USED.has(k)),
  }
}

/** Splits the Arguments field like a shell: spaces separate, "…" or '…' keep spaces in one arg. */
export function splitArgs(text: string): string[] {
  const out: string[] = []
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) out.push(m[1] ?? m[2] ?? m[3])
  return out
}

/** The inverse of splitArgs: quotes an arg only when it has spaces or is empty. */
export function joinArgs(args: string[]): string {
  return args.map((a) => (a === '' || /\s/.test(a) ? (a.includes('"') ? `'${a}'` : `"${a}"`) : a)).join(' ')
}
