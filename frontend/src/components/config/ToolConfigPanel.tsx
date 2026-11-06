import { useState, useEffect } from 'react'
import type { ToolNodeData, ConnectionNodeData, FlowNode, FlowEdge } from '../../types'
import { API_BASE } from '../../types'
import type { Node } from '@xyflow/react'
import { ConnectionIcon } from '../ConnectionIcon'
import { ApiKeyField } from './ApiKeyField'
import { ToolSecretFields } from './ToolSecretFields'
import { ToolOptionFields } from './ToolOptionFields'
import { McpToolsPicker, ToolParametersInfo } from './ToolParameters'
import { getToolSpec } from '../../utils/toolCatalog'

interface Props {
  activeNode: FlowNode
  nodes: FlowNode[]
  edges: FlowEdge[]
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
  onEditCustomTool?: (toolId: string) => void
}

// MCP tool ids that use a connection node for credentials (never store creds directly)
const MCP_DB_TOOLS = new Set(['mcp_postgres', 'mcp_database'])

// All OOTB MCP servers that have guided config fields

/** How a built-in MCP server is started, from its catalog default config. */
function launcherNote(defaults?: Record<string, any>): string {
  if (defaults?.transport === 'http') return 'Runs on the vendor\'s own remote MCP server; nothing is installed here.'
  if (defaults?.command === 'uvx') return 'Requires uvx (uv) on the server PATH. The pinned package is downloaded on first run.'
  return 'Requires npx on the server PATH. The pinned package is downloaded on first run.'
}
const OOTB_MCP_TOOLS = new Set([
  'mcp_filesystem', 'mcp_github', 'mcp_brave_search', 'mcp_puppeteer',
  'mcp_git', 'mcp_fetch', 'mcp_sequential_thinking', 'mcp_firecrawl',
  'mcp_sqlite', 'mcp_memory', 'mcp_sentry', 'mcp_gitlab', 'mcp_gdrive', 'mcp_google_maps',
  'mcp_aws_kb', 'mcp_everything', 'mcp_pdf',
  'mcp_notion', 'mcp_linear', 'mcp_jira', 'mcp_docker', 'mcp_podman', 'mcp_redis', 'mcp_openapi',
  'mcp_kafka', 'mcp_remote_http', 'mcp_remote_sse', 'mcp_slack', 'mcp_trello', 'mcp_asana',
])

/** Guided config panel for all OOTB MCP servers */
function OotbMcpConfigFields({
  toolId,
  config,
  readOnly,
  onChange,
}: {
  toolId: string
  config: Record<string, any>
  readOnly?: boolean
  onChange: (patch: Record<string, any>) => void
}) {
  const field = (
    label: string,
    key: string,
    placeholder: string,
    type: 'text' | 'password' = 'text',
    hint?: string,
  ) => (
    <div className="form-group" key={key}>
      <label className="field-label">{label}</label>
      {type === 'password' ? (
        // Credentials come from the vault — the node stores a "secret://" ref
        <ApiKeyField kind="tool" provider={toolId.replace(/^mcp_/, '')} value={config[key]} readOnly={readOnly}
          placeholder={placeholder} secretName={label} emptyLabel="— Not set —"
          onChange={(v) => onChange({ [key]: v })} />
      ) : (
        <input
          type={type}
          className="field-input"
          placeholder={placeholder}
          value={config[key] ?? ''}
          disabled={readOnly}
          onChange={(e) => onChange({ [key]: e.target.value })}
        />
      )}
      {hint && <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>{hint}</div>}
    </div>
  )

  // ── Original four ──────────────────────────────────────────────────────────
  if (toolId === 'mcp_filesystem') {
    return (
      <>
        {field('Allowed Directory', 'allowed_path', '/Users/you/projects/my-app', 'text',
          'Root directory the AI may read/write. Options: read_file, write_file, list_directory, create_directory, move_file, search_files, get_file_info.')}
        {field('Default Tool', 'tool_name', 'read_file  (leave blank for default)')}
      </>
    )
  }
  if (toolId === 'mcp_github') {
    return (
      <>
        {field('GitHub Personal Access Token', 'github_token', 'ghp_…', 'password',
          'github.com/settings/tokens — needs repo scope for private repos.')}
        {field('Default Tool', 'tool_name', 'search_repositories  (leave blank for default)', 'text',
          "GitHub's own server (api.githubcopilot.com). Options include search_repositories, search_code, get_file_contents, list_commits, list_issues; use Discover tools for the full list.")}
      </>
    )
  }
  if (toolId === 'mcp_brave_search') {
    return (
      <>
        {field('Brave Search API Key', 'brave_api_key', 'BSA…', 'password',
          'brave.com/search/api — 2,000 free queries/month.')}
        {field('Default Tool', 'tool_name', 'brave_web_search  (leave blank for default)', 'text',
          'Options: brave_web_search, brave_local_search.')}
      </>
    )
  }
  if (toolId === 'mcp_puppeteer') {
    return (
      <>
        {field('Default Tool', 'tool_name', 'puppeteer_navigate  (leave blank for default)', 'text',
          'Options: puppeteer_navigate, puppeteer_screenshot, puppeteer_click, puppeteer_fill, puppeteer_evaluate, puppeteer_select, puppeteer_hover.')}
        {field('Launch Options (JSON)', 'launch_options', '{"headless": true}')}
      </>
    )
  }

  // ── Article gaps ───────────────────────────────────────────────────────────
  if (toolId === 'mcp_git') {
    return (
      <>
        {field('Repository Path', 'repo_path', '/Users/you/projects/my-app', 'text',
          'Absolute path to the local Git repository. Defaults to "." (current working directory).')}
        {field('Default Tool', 'tool_name', 'git_log  (leave blank for default)', 'text',
          'Options: git_log, git_diff, git_status, git_show, git_blame, git_branch, git_commit.')}
      </>
    )
  }
  if (toolId === 'mcp_fetch') {
    return (
      <>
        {field('Default Tool', 'tool_name', 'fetch  (leave blank for default)', 'text',
          'Input is the URL to fetch. Returns clean readable text or markdown.')}
      </>
    )
  }
  if (toolId === 'mcp_sequential_thinking') {
    return (
      <>
        {field('Total Thought Steps', 'total_thoughts', '5', 'text',
          'How many reasoning steps the model should take. Increase for very complex problems.')}
        {field('Default Tool', 'tool_name', 'sequentialthinking  (leave blank for default)')}
      </>
    )
  }
  if (toolId === 'mcp_firecrawl') {
    return (
      <>
        {field('Firecrawl API Key', 'firecrawl_api_key', 'fc-…', 'password',
          'Get a key at firecrawl.dev. Handles JS-rendered pages and SPAs.')}
        {field('Default Tool', 'tool_name', 'firecrawl_scrape  (leave blank for default)', 'text',
          'Options: firecrawl_scrape, firecrawl_crawl, firecrawl_search, firecrawl_extract.')}
      </>
    )
  }

  // ── Official @modelcontextprotocol servers ─────────────────────────────────
  if (toolId === 'mcp_sqlite') {
    return (
      <>
        {field('Database File Path', 'db_path', './data.db', 'text',
          'Path to the SQLite .db file. Created if it does not exist.')}
        {field('Default Tool', 'tool_name', 'list-tables  (leave blank for default)', 'text',
          'Options: list-tables, describe-table, read-query, write-query, create-table, append-insight.')}
      </>
    )
  }
  if (toolId === 'mcp_memory') {
    return (
      <>
        {field('Default Tool', 'tool_name', 'create_entities  (leave blank for default)', 'text',
          'Options: create_entities, create_relations, add_observations, delete_entities, delete_observations, delete_relations, read_graph, search_nodes, open_nodes.')}
      </>
    )
  }
  if (toolId === 'mcp_sentry') {
    return (
      <>
        {field('Sentry Auth Token', 'sentry_auth_token', 'sntrys_…', 'password',
          'Create a token at sentry.io/settings/auth-tokens with org:read and project:read scopes.')}
        {field('Default Tool', 'tool_name', 'get_sentry_issue  (leave blank for default)', 'text',
          'Options: get_sentry_issue, list_sentry_issues.')}
      </>
    )
  }
  if (toolId === 'mcp_gitlab') {
    return (
      <>
        {field('GitLab Personal Access Token', 'gitlab_token', 'glpat-…', 'password',
          'gitlab.com/profile/personal_access_tokens — needs api scope.')}
        {field('GitLab API URL', 'gitlab_api_url', 'https://gitlab.com/api/v4', 'text',
          'Change for self-hosted instances, e.g. https://git.mycompany.com/api/v4.')}
        {field('Default Tool', 'tool_name', 'list_projects  (leave blank for default)', 'text',
          'Plain input is the project search term. Use Discover tools for every GitLab tool.')}
      </>
    )
  }
  if (toolId === 'mcp_gdrive') {
    return (
      <>
        {field('Credentials File Path', 'gdrive_credentials_file', '/path/to/credentials.json', 'text',
          'Path to your Google OAuth2 credentials JSON. Download from console.cloud.google.com.')}
        {field('Default Tool', 'tool_name', 'search  (leave blank for default)', 'text',
          'Options: search, read_file, list_files.')}
      </>
    )
  }
  if (toolId === 'mcp_google_maps') {
    return (
      <>
        {field('Google Maps API Key', 'google_maps_api_key', 'AIza…', 'password',
          'Create an API key in Google Cloud Console and enable Maps APIs.')}
        {field('Default Tool', 'tool_name', 'maps_search_places  (leave blank for default)', 'text',
          'Use discovered tools for specific actions (search, geocode, directions, place details).')}
      </>
    )
  }
  if (toolId === 'mcp_aws_kb') {
    return (
      <>
        {field('AWS Access Key ID', 'aws_access_key_id', 'AKIA...', 'password')}
        {field('AWS Secret Access Key', 'aws_secret_access_key', '', 'password')}
        {field('AWS Region', 'aws_region', 'us-east-1', 'text')}
        {field('Bedrock Knowledge Base ID', 'bedrock_kb_id', 'KB12345678', 'text')}
        {field('Default Tool', 'tool_name', 'QueryKnowledgeBases  (leave blank for default)', 'text',
          'Options: QueryKnowledgeBases, ListKnowledgeBases, AgenticQueryKnowledgeBases (managed knowledge bases).')}
      </>
    )
  }
  if (toolId === 'mcp_everything') {
    return (
      <>
        {field('Default Tool', 'tool_name', 'echo  (leave blank for default)', 'text',
          'Reference/test server that exposes many MCP protocol features.')}
      </>
    )
  }
  if (toolId === 'mcp_pdf') {
    return (
      <>
        {field('Default Tool', 'tool_name', 'read_pdf  (leave blank for default)', 'text',
          'Use discovered tools for extraction and page-level access depending on server version.')}
      </>
    )
  }

  // ── Community / vendor MCPs ────────────────────────────────────────────────
  if (toolId === 'mcp_notion') {
    return (
      <>
        {field('Notion Integration Token', 'notion_token', 'secret_…', 'password',
          'Create an internal integration at notion.so/my-integrations. Share pages with the integration to grant access.')}
        {field('Default Tool', 'tool_name', 'API-post-search  (leave blank for default)', 'text',
          'Options: API-post-search, API-get-page, API-patch-page, API-post-page, API-get-database, API-post-database-query.')}
      </>
    )
  }
  if (toolId === 'mcp_linear') {
    return (
      <>
        {field('Linear API Key', 'linear_api_key', 'lin_api_…', 'password',
          'Create a Personal API key at linear.app/settings/api.')}
        {field('Default Tool', 'tool_name', 'list_issues  (leave blank for default)', 'text',
          "Linear's own server (mcp.linear.app). Use Discover tools for its exact tool names.")}
      </>
    )
  }
  if (toolId === 'mcp_jira') {
    return (
      <>
        {field('Jira URL', 'jira_url', 'https://yourcompany.atlassian.net', 'text')}
        {field('Jira Username', 'jira_username', 'you@company.com')}
        {field('Jira API Token', 'jira_api_token', 'ATATT…', 'password',
          'Create a token at id.atlassian.com/manage-profile/security/api-tokens.')}
        {field('Default Tool', 'tool_name', 'jira_get_issue  (leave blank for default)', 'text',
          'Options include jira_get_issue, jira_search, jira_create_issue, jira_update_issue, jira_transition_issue.')}
      </>
    )
  }
  if (toolId === 'mcp_slack') {
    return (
      <>
        {field('Slack Bot Token', 'slack_bot_token', 'xoxb-…', 'password',
          'Create a Slack app token with channels:read, channels:history, chat:write, users:read scopes.')}
        {field('Slack Team ID', 'slack_team_id', 'T01234567', 'text')}
        {field('Allowed Channel IDs', 'slack_channel_ids', 'C01234567,C76543210', 'text',
          'Optional comma-separated list to restrict which channels the server can use.')}
        {field('Default Tool', 'tool_name', 'slack_list_channels  (leave blank for default)', 'text',
          'Options: slack_list_channels, slack_post_message, slack_get_channel_history, slack_get_users, slack_get_user_profile.')}
      </>
    )
  }
  if (toolId === 'mcp_trello') {
    return (
      <>
        {field('Trello API Key', 'trello_api_key', 'your-trello-api-key', 'password')}
        {field('Trello Token', 'trello_token', 'your-trello-token', 'password')}
        {field('Default Tool', 'tool_name', 'list_boards  (leave blank for default)', 'text',
          'Use discovered tools to pick exact operations (boards, cards, lists, labels, checklists).')}
      </>
    )
  }
  if (toolId === 'mcp_asana') {
    return (
      <>
        {field('Asana Access Token', 'asana_access_token', '0/your-personal-token', 'password')}
        {field('Default Workspace GID', 'asana_mcp_default_workspace', '1200000000000001', 'text',
          'Optional workspace id used by list/search tools when not provided in arguments.')}
        {field('Write Mode', 'asana_mcp_write_mode', 'read_only', 'text',
          'read_only (default), restricted, or full.')}
        {field('Default Tool', 'tool_name', 'asana_list_tasks  (leave blank for default)', 'text',
          'Common tools: asana_list_tasks, asana_get_task, asana_add_comment, asana_create_task.')}
      </>
    )
  }
  if (toolId === 'mcp_docker') {
    return (
      <>
        {field('Docker Host', 'docker_host', 'unix:///var/run/docker.sock  (leave blank for the default)', 'text')}
        {field('Default Tool', 'tool_name', 'list_containers  (leave blank for default)', 'text',
          'Options include list_containers, run_container, stop_container, fetch_container_logs, list_images, pull_image, list_volumes. Requires Docker running.')}
      </>
    )
  }
  if (toolId === 'mcp_podman') {
    return (
      <>
        {field('Podman Socket Path', 'podman_socket',
          '~/.local/share/containers/podman/machine/podman.sock', 'text',
          'Leave blank to auto-detect the Podman Desktop socket (~/.local/share/containers/podman/machine/podman.sock on macOS). Uses mcp-server-docker via DOCKER_HOST under the hood — Podman is Docker-API compatible.')}
        {field('Default Tool', 'tool_name', 'list_containers  (leave blank for default)', 'text',
          'Options include list_containers, run_container, stop_container, fetch_container_logs, list_images, pull_image.')}
      </>
    )
  }
  if (toolId === 'mcp_redis') {
    return (
      <>
        {field('Redis URL', 'redis_url', 'redis://localhost:6379', 'text',
          'Format: redis://[:password@]host[:port][/db-number]. Defaults to localhost:6379.')}
        {field('Default Tool', 'tool_name', 'get  (leave blank for default)', 'text',
          'Options include get, set, delete, scan_keys, type, hget, hset, hgetall, expire, info.')}
      </>
    )
  }
  if (toolId === 'mcp_openapi') {
    return (
      <>
        {field('OpenAPI Spec URL', 'openapi_spec_url', 'https://api.example.com/openapi.json', 'text',
          'URL or local path to an OpenAPI 3.x spec.')}
        {field('API Base URL', 'api_base_url', 'https://api.example.com', 'text', 'Where the API calls go.')}
        {field('API Token', 'api_token', 'sent as Authorization: Bearer …', 'password')}
        {field('Default Tool', 'tool_name', 'list-api-endpoints  (leave blank for default)', 'text',
          'Options: list-api-endpoints, get-api-endpoint-schema, invoke-api-endpoint ("Tools: one per endpoint" names each endpoint instead).')}
      </>
    )
  }
  if (toolId === 'mcp_kafka') {
    return (
      <>
        {field('Bootstrap Servers', 'kafka_bootstrap_servers', 'localhost:9092', 'text',
          'Comma-separated list of Kafka broker addresses. Use this for a local or self-hosted cluster. Leave blank when connecting via Confluent Cloud.')}
        {field('Confluent Cloud API Key', 'confluent_cloud_api_key', 'ABCDEFGH12345678', 'password',
          'Confluent Cloud API key. Leave blank for a local Kafka cluster. Create at confluent.cloud → API Keys.')}
        {field('Confluent Cloud API Secret', 'confluent_cloud_api_secret', '', 'password',
          'Confluent Cloud API secret paired with the key above.')}
        {field('Default Tool', 'tool_name', 'list-topics  (leave blank for default)', 'text',
          'Options: list-topics, produce-message, consume-messages, list-consumer-groups, describe-topic.')}
      </>
    )
  }
  if (toolId === 'mcp_remote_http') {
    return (
      <>
        {field('Remote URL', 'url', 'https://example.com/mcp', 'text',
          'Streamable HTTP endpoint. The client automatically falls back when the server only supports legacy transport.')}
        {field('Headers (JSON)', 'headers', '{"Authorization":"Bearer ..."}', 'text',
          'Optional request headers as JSON for auth and custom routing.')}
        {field('Default Tool', 'tool_name', 'query  (leave blank for default)', 'text',
          'When mcp_tools are not selected, this tool name is called by default.')}
      </>
    )
  }
  if (toolId === 'mcp_remote_sse') {
    return (
      <>
        {field('Remote SSE URL', 'url', 'https://example.com/sse', 'text',
          'Legacy HTTP+SSE endpoint URL.')}
        {field('Headers (JSON)', 'headers', '{"Authorization":"Bearer ..."}', 'text',
          'Optional request headers as JSON for auth and custom routing.')}
        {field('Default Tool', 'tool_name', 'query  (leave blank for default)', 'text',
          'When mcp_tools are not selected, this tool name is called by default.')}
      </>
    )
  }

  // Generic fallback for any future tool
  return (
    <>{field('Default Tool', 'tool_name', 'query  (leave blank for default)')}</>
  )
}

const GUIDED_TOOL_IDS = new Set(['docling', 'crawl4ai', 'instructor', 'guardrails', 'python_interpreter'])

/** Which version of a custom tool this node runs: the latest, or a pinned one. */
function ToolVersionPicker({ toolId, value, readOnly, onChange }: {
  toolId: string; value: number | undefined; readOnly?: boolean; onChange: (v: number | undefined) => void
}) {
  const [versions, setVersions] = useState<{ version: number; note: string | null }[]>([])
  const [current, setCurrent] = useState<number | null>(null)
  useEffect(() => {
    fetch(`${API_BASE}/api/custom-tools/${toolId}/versions`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) { setVersions(d.versions); setCurrent(d.current) } })
      .catch(() => {})
  }, [toolId])
  if (current === null) return null
  return (
    <div className="form-group">
      <label className="field-label">Tool version</label>
      <select className="field-select" value={value ?? ''} disabled={readOnly}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : undefined)}>
        <option value="">Latest (v{current})</option>
        {versions.map((v) => <option key={v.version} value={v.version}>v{v.version}{v.note ? ` — ${v.note}` : ''}</option>)}
      </select>
      <span className="field-hint">Pin a version so later changes to the tool don't affect this pipeline.</span>
    </div>
  )
}

export function ToolConfigPanel({ activeNode, nodes, edges, onUpdate, onDelete, onSave, readOnly, onEditCustomTool }: Props) {
  const data = activeNode.data as ToolNodeData
  const isCustomTool = data.toolId?.startsWith('custom_')
  const isMcpDb = data.toolType === 'mcp' && MCP_DB_TOOLS.has(data.toolId)
  const isOotbMcp = data.toolType === 'mcp' && OOTB_MCP_TOOLS.has(data.toolId)
  const isGuidedTool = data.toolType === 'tool' && GUIDED_TOOL_IDS.has(data.toolId)

  // Sandbox isolation status (python_interpreter only)
  const [sandboxRuntime, setSandboxRuntime] = useState<string | null | undefined>(undefined)
  useEffect(() => {
    if (data.toolId !== 'python_interpreter') return
    fetch(`${API_BASE}/api/tools/runtime-status`)
      .then((r) => r.json())
      .then((s) => setSandboxRuntime(s?.sandbox?.container_runtime ?? null))
      .catch(() => setSandboxRuntime(undefined))
  }, [data.toolId])

  // Docling test-parse state
  const [parseStatus, setParseStatus] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [parsePreview, setParsePreview] = useState<string>('')

  async function runTestParse() {
    const inputPath = (data.config?.input_path || '').trim()
    if (!inputPath) { setParseStatus('error'); setParsePreview('Set an Input File Path first.'); return }
    setParseStatus('loading')
    setParsePreview('')
    try {
      const res = await fetch(`${API_BASE}/api/tools/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tool_type: 'docling', input_text: inputPath, config: data.config || {} }),
      })
      const json = await res.json()
      if (json.success) {
        setParseStatus('done')
        setParsePreview(json.output ?? '')
      } else {
        setParseStatus('error')
        setParsePreview(json.output ?? 'Unknown error')
      }
    } catch (e: any) {
      setParseStatus('error')
      setParsePreview(`Network error: ${e?.message}`)
    }
  }

  // Resolve the linked connection node (if any) purely for display
  const linkedConnNode = isMcpDb
    ? (() => {
        const linkedIds = edges
          .filter((e) => e.source === activeNode.id || e.target === activeNode.id)
          .map((e) => (e.source === activeNode.id ? e.target : e.source))
        return nodes.find(
          (n) => n.type === 'connection' && linkedIds.includes(n.id),
        ) as Node<ConnectionNodeData, 'connection'> | undefined
      })()
    : undefined

  // Config to display in the JSON editor — strip ALL credential fields for MCP DB tools.
  // Also sanitize the args array: remove any entry that looks like a postgres:// DSN.
  const displayConfig = isMcpDb
    ? (() => {
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        const { connection_string, host, port, database, user, password, ssl, ...mcpOnly } = data.config || {}
        // Strip DSN-like strings from args (they contain credentials)
        if (Array.isArray(mcpOnly.args)) {
          mcpOnly.args = mcpOnly.args.filter(
            (a: unknown) => typeof a !== 'string' || !a.startsWith('postgresql://')
          )
        }
        return mcpOnly
      })()
    : data.config || {}

  return (
    <div className="bottom-config-grid">
      {/* 1. Tool Identity */}
      <div className="config-card">
        <h4 className="card-heading">1. Tool Identification</h4>
        <div className="form-group">
          <label className="field-label">Tool Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Type</label>
          <span className="field-readonly-badge">{data.toolType.toUpperCase()}</span>
        </div>
      </div>

      {/* 2. Tool Description */}
      <div className="config-card">
        <h4 className="card-heading">2. Tool Description</h4>
        <div className="form-group">
          <label className="field-label">Description for LLM Agent</label>
          <textarea rows={3} className="field-textarea" value={data.description} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { description: e.target.value })} />
        </div>
      </div>

      {/* 3. Parameters — guided fields for OOTB MCPs, connection ref for DB MCPs, raw JSON for others */}
      <div className="config-card">
        <h4 className="card-heading">3. Parameters &amp; Auth</h4>

        {isOotbMcp ? (
          <>
            <OotbMcpConfigFields
              toolId={data.toolId}
              config={data.config || {}}
              readOnly={readOnly}
              onChange={(patch) => onUpdate(activeNode.id, { config: { ...data.config, ...patch } })}
            />
            <ToolOptionFields
              toolId={data.toolId}
              config={data.config || {}}
              readOnly={readOnly}
              onChange={(patch) => onUpdate(activeNode.id, { config: { ...data.config, ...patch } })}
            />
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 8, padding: '6px 8px', background: '#f8fafc', borderRadius: 4, border: '1px solid #e2e8f0' }}>
              💡 {launcherNote(getToolSpec(data.toolId)?.default_config)}
            </div>
          </>
        ) : isMcpDb ? (
          <>
            <div className="form-group">
              <label className="field-label">Data Source Connection</label>
              {linkedConnNode ? (() => {
                const status = linkedConnNode.data.status
                const tone = status === 'connected'
                  ? { border: '#bbf7d0', bg: '#f0fdf4', fg: '#166534', accent: '#15803d', text: '🟢 Live' }
                  : status === 'error'
                    ? { border: '#fecaca', bg: '#fef2f2', fg: '#991b1b', accent: '#b91c1c', text: '🔴 Error' }
                    : { border: '#fde68a', bg: '#fffbeb', fg: '#92400e', accent: '#b45309', text: '🟡 Untested' }
                return (
                  <>
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '8px 10px', borderRadius: 6,
                      border: `1px solid ${tone.border}`, background: tone.bg,
                      fontSize: 12, fontWeight: 600, color: tone.fg,
                    }}>
                      <ConnectionIcon type={linkedConnNode.data.connection_type} />
                      <span>{linkedConnNode.data.label}</span>
                      <span style={{ marginLeft: 'auto', fontWeight: 400, color: tone.accent, fontSize: 11 }}>
                        {tone.text}
                      </span>
                    </div>
                    {status === 'error' && linkedConnNode.data.status_msg && (
                      <span className="field-hint" style={{ display: 'block', marginTop: 4, color: tone.accent }}>
                        {linkedConnNode.data.status_msg.slice(0, 120)}
                      </span>
                    )}
                  </>
                )
              })() : (
                <div style={{
                  padding: '8px 10px', borderRadius: 6,
                  border: '1px solid #fde68a', background: '#fffbeb',
                  fontSize: 12, color: '#92400e',
                }}>
                  ⚠ No connection node linked. Draw an edge from a Connection node to this tool.
                </div>
              )}
            </div>
            {linkedConnNode && (
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                Credentials are resolved from the connection node at runtime — they are never stored here.
              </div>
            )}
            {Object.keys(displayConfig).length > 0 && (
              <div className="form-group" style={{ marginTop: 10 }}>
                <label className="field-label">MCP Server Config</label>
                <textarea rows={3} className="field-textarea code-font"
                  value={JSON.stringify(displayConfig, null, 2)}
                  disabled={readOnly}
                  onChange={(e) => {
                    try {
                      const parsed = JSON.parse(e.target.value)
                      onUpdate(activeNode.id, { config: { ...data.config, ...parsed } })
                    } catch { /* typing */ }
                  }} />
              </div>
            )}
          </>
        ) : isGuidedTool && data.toolId === 'docling' ? (
          <>
            <div className="form-group">
              <label className="field-label">Input Path — file or folder</label>
              <input
                type="text"
                className="field-input"
                placeholder="/path/to/document.pdf  or  /path/to/folder/"
                value={data.config?.input_path ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, input_path: e.target.value } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                Point to a <strong>single file</strong> (PDF, DOCX, PPTX, XLSX, HTML, TXT, MD, PNG/JPG…) <em>or</em> a <strong>folder</strong> — all supported files in the folder are parsed automatically. You can also pass the path as the tool input at runtime.
              </div>
            </div>
            <div className="form-group">
              <label className="field-label">Output Path <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional — file or folder)</span></label>
              <input
                type="text"
                className="field-input"
                placeholder="/path/to/output.md  or  /path/to/out_folder/"
                value={data.config?.output_path ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, output_path: e.target.value } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                Leave blank — content is returned to the agent in-context.<br />
                Set a <strong>filename</strong> (e.g. <code>out/result.md</code>) to save a single file.<br />
                Set a <strong>folder</strong> (e.g. <code>out/</code>) to save one file per source when parsing a directory.
              </div>
            </div>
            <div className="form-group">
              <label className="field-label">Output Format</label>
              <select
                className="field-input"
                value={data.config?.output_format ?? 'markdown'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, output_format: e.target.value } })}
              >
                <option value="markdown">Markdown</option>
                <option value="json">JSON</option>
              </select>
            </div>
            <div className="form-group" style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={!!data.config?.ocr}
                  disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, ocr: e.target.checked } })}
                />
                Enable OCR
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={data.config?.export_tables !== false}
                  disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, export_tables: e.target.checked } })}
                />
                Extract Tables
              </label>
            </div>
            <div className="form-group" style={{ marginTop: 10 }}>
              <label className="field-label">
                Max Chars to Inject{' '}
                <span style={{ fontWeight: 400, color: '#94a3b8' }}>(0 = unlimited)</span>
              </label>
              <input
                type="number"
                className="field-input"
                placeholder="80000"
                min={0}
                step={10000}
                value={data.config?.max_chars ?? 80000}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, max_chars: parseInt(e.target.value, 10) || 0 } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                Caps how much parsed text is sent to the LLM in one go.{' '}
                <strong>80 000 chars ≈ 20k tokens</strong> — safe for GPT-4o (128k) and Claude (200k).{' '}
                For larger documents, use a <strong>RAG pipeline</strong> (Retriever node) instead.
              </div>
            </div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 6, padding: '6px 8px', background: '#f8fafc', borderRadius: 4, border: '1px solid #e2e8f0' }}>
              💡 Requires <code>pip install docling</code> on the server. Supports PDF, DOCX, PPTX, HTML, images (PNG/JPG) and more.
            </div>

            {/* ── Test Parse button + preview ── */}
            <div style={{ marginTop: 12 }}>
              <button
                type="button"
                disabled={readOnly || parseStatus === 'loading'}
                onClick={runTestParse}
                style={{
                  width: '100%', padding: '7px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
                  background: parseStatus === 'loading' ? '#94a3b8' : '#3b82f6',
                  color: '#fff', fontSize: 13, fontWeight: 600,
                }}
              >
                {parseStatus === 'loading' ? '⏳ Parsing…' : '▶ Test Parse Now'}
              </button>
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 4, textAlign: 'center' }}>
                Runs Docling immediately so you can verify the output before using it in a pipeline.
              </div>
            </div>

            {parseStatus !== 'idle' && parsePreview && (
              <div style={{
                marginTop: 10, borderRadius: 6, border: `1px solid ${parseStatus === 'error' ? '#fca5a5' : '#bbf7d0'}`,
                background: parseStatus === 'error' ? '#fef2f2' : '#f0fdf4',
              }}>
                <div style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '5px 10px', borderBottom: `1px solid ${parseStatus === 'error' ? '#fca5a5' : '#bbf7d0'}`,
                  fontSize: 11, fontWeight: 600, color: parseStatus === 'error' ? '#b91c1c' : '#166534',
                }}>
                  <span>{parseStatus === 'error' ? '❌ Parse failed' : '✅ Parsed successfully'}</span>
                  <button
                    type="button"
                    onClick={() => { setParseStatus('idle'); setParsePreview('') }}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, color: '#64748b' }}
                  >✕</button>
                </div>
                <textarea
                  readOnly
                  rows={8}
                  className="field-textarea code-font"
                  style={{ margin: 0, borderRadius: '0 0 6px 6px', border: 'none', background: 'transparent', fontSize: 11, resize: 'vertical' }}
                  value={parsePreview}
                />
              </div>
            )}
          </>
        ) : isGuidedTool && data.toolId === 'crawl4ai' ? (
          <>
            <div className="form-group">
              <label className="field-label">URL to Crawl</label>
              <input type="text" className="field-input"
                placeholder="https://example.com"
                value={data.config?.url ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, url: e.target.value } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                You can also pass the URL as the tool input at runtime. Handles JavaScript-rendered pages automatically.
              </div>
            </div>
            <div className="form-group">
              <label className="field-label">Output Format</label>
              <select className="field-input"
                value={data.config?.output_format ?? 'markdown'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, output_format: e.target.value } })}>
                <option value="markdown">Markdown</option>
                <option value="json">Structured JSON</option>
              </select>
            </div>
            <div className="form-group">
              <label className="field-label">CSS Selector <span style={{ fontWeight: 400, color: '#94a3b8' }}>(optional)</span></label>
              <input type="text" className="field-input"
                placeholder="article.content  or  #main-body"
                value={data.config?.css_selector ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, css_selector: e.target.value } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                Scope the crawl to a specific part of the page. Leave blank for full page.
              </div>
            </div>
            <div className="form-group">
              <label className="field-label">Max Chars to Inject <span style={{ fontWeight: 400, color: '#94a3b8' }}>(0 = unlimited)</span></label>
              <input type="number" className="field-input"
                placeholder="80000" min={0} step={10000}
                value={data.config?.max_chars ?? 80000}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, max_chars: parseInt(e.target.value, 10) || 0 } })}
              />
            </div>
            <div className="form-group" style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                <input type="checkbox"
                  checked={!!data.config?.screenshot}
                  disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, screenshot: e.target.checked } })}
                />
                Capture Screenshot
              </label>
            </div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 6, padding: '6px 8px', background: '#f8fafc', borderRadius: 4, border: '1px solid #e2e8f0' }}>
              💡 Requires <code>pip install crawl4ai &amp;&amp; python -m crawl4ai.install</code>. Uses a headless Chromium browser — handles SPAs, lazy-loaded content, and JS-rendered pages.
            </div>
          </>
        ) : isGuidedTool && data.toolId === 'python_interpreter' ? (
          <>
            {sandboxRuntime !== undefined && (
              <div style={{
                fontSize: 11, padding: '6px 8px', borderRadius: 4, marginBottom: 8,
                border: `1px solid ${sandboxRuntime ? '#bbf7d0' : '#fde68a'}`,
                background: sandboxRuntime ? '#f0fdf4' : '#fffbeb',
                color: sandboxRuntime ? '#166534' : '#92400e',
              }}>
                {sandboxRuntime
                  ? `🟢 Container engine available (${sandboxRuntime}) — code runs isolated.`
                  : '⚠ No podman/docker engine reachable — "auto" falls back to a local subprocess with NO isolation.'}
              </div>
            )}
            <div className="form-group">
              <label className="field-label">Backend</label>
              <select className="field-input"
                value={data.config?.backend ?? 'auto'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, backend: e.target.value } })}>
                <option value="auto">Auto — container if available, else local</option>
                <option value="container">Container only (podman/docker)</option>
                <option value="local">Local subprocess (no isolation)</option>
              </select>
            </div>
            <div className="form-group">
              <label className="field-label">Timeout (seconds)</label>
              <input type="number" className="field-input" min={1} max={300}
                value={data.config?.timeout ?? 10}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, timeout: parseInt(e.target.value, 10) || 10 } })} />
            </div>
            <div className="form-group">
              <label className="field-label">Memory limit (MB)</label>
              <input type="number" className="field-input" min={32} step={32}
                value={data.config?.memory_mb ?? 256}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, memory_mb: parseInt(e.target.value, 10) || 256 } })} />
            </div>
            <div className="form-group">
              <label className="field-label">Container image</label>
              <input type="text" className="field-input"
                placeholder="python:3.12-slim"
                value={data.config?.image ?? 'python:3.12-slim'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, image: e.target.value } })} />
            </div>
            <div className="form-group">
              <label className="field-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input type="checkbox"
                  checked={!!data.config?.allow_network}
                  disabled={readOnly}
                  onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, allow_network: e.target.checked } })} />
                Allow network access (container backend)
              </label>
            </div>
          </>
        ) : isGuidedTool && data.toolId === 'instructor' ? (
          <>
            <div className="form-group">
              <label className="field-label">Extraction Schema (JSON)</label>
              <textarea rows={4} className="field-textarea code-font"
                placeholder={'{\n  "name": "string",\n  "age": "int",\n  "email": "string"\n}'}
                value={data.config?.schema_json ?? '{"name": "string", "age": "int"}'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, schema_json: e.target.value } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                Define the fields to extract. Supported types: <code>string</code>, <code>int</code>, <code>float</code>, <code>bool</code>, <code>list</code>, <code>dict</code>.
              </div>
            </div>
            <div className="form-group">
              <label className="field-label">Model</label>
              <input type="text" className="field-input"
                placeholder="gpt-4o-mini"
                value={data.config?.model ?? 'gpt-4o-mini'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, model: e.target.value } })}
              />
            </div>
            <div className="form-group">
              <label className="field-label">API Key</label>
              <input type="password" className="field-input"
                placeholder="sk-… (or set OPENAI_API_KEY env var)"
                value={data.config?.api_key ?? ''}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, api_key: e.target.value } })}
              />
            </div>
            <div className="form-group">
              <label className="field-label">Max Retries</label>
              <input type="number" className="field-input"
                placeholder="3" min={1} max={5}
                value={data.config?.max_retries ?? 3}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, max_retries: parseInt(e.target.value, 10) || 3 } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                Instructor automatically retries if the LLM output doesn't match the schema.
              </div>
            </div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 6, padding: '6px 8px', background: '#f8fafc', borderRadius: 4, border: '1px solid #e2e8f0' }}>
              💡 Requires <code>pip install instructor</code>. Connect downstream of a Docling or Crawl4AI node to extract structured data from parsed documents.
            </div>
          </>
        ) : isGuidedTool && data.toolId === 'guardrails' ? (
          <>
            <div className="form-group">
              <label className="field-label">Mode</label>
              <select className="field-input"
                value={data.config?.mode ?? 'output'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, mode: e.target.value } })}>
                <option value="input">Input only</option>
                <option value="output">Output only</option>
                <option value="both">Both input &amp; output</option>
              </select>
            </div>
            <div className="form-group">
              <label className="field-label">Checks (comma-separated)</label>
              <input type="text" className="field-input"
                placeholder="detect_pii,toxic_language,no_profanity"
                value={data.config?.checks ?? 'detect_pii,toxic_language'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, checks: e.target.value } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                Available: <code>detect_pii</code>, <code>toxic_language</code>, <code>no_profanity</code>
              </div>
            </div>
            <div className="form-group">
              <label className="field-label">Action on Violation</label>
              <select className="field-input"
                value={data.config?.action ?? 'warn'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, action: e.target.value } })}>
                <option value="warn">Warn — flag but pass through</option>
                <option value="block">Block — stop pipeline</option>
                <option value="redact">Redact — remove violations</option>
              </select>
            </div>
            <div className="form-group">
              <label className="field-label">PII Entities to Detect</label>
              <input type="text" className="field-input"
                placeholder="PERSON,EMAIL,PHONE_NUMBER,LOCATION"
                value={data.config?.pii_entities ?? 'PERSON,EMAIL,PHONE_NUMBER,LOCATION'}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, pii_entities: e.target.value } })}
              />
            </div>
            <div className="form-group">
              <label className="field-label">Toxicity Threshold (0–1)</label>
              <input type="number" className="field-input"
                placeholder="0.5" min={0} max={1} step={0.05}
                value={data.config?.toxicity_threshold ?? 0.5}
                disabled={readOnly}
                onChange={(e) => onUpdate(activeNode.id, { config: { ...data.config, toxicity_threshold: parseFloat(e.target.value) || 0.5 } })}
              />
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                Score above this triggers a violation. Lower = stricter. Uses <code>detoxify</code> if installed, otherwise a keyword heuristic.
              </div>
            </div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 6, padding: '6px 8px', background: '#f8fafc', borderRadius: 4, border: '1px solid #e2e8f0' }}>
              💡 PII detection works with zero extra dependencies. For ML-based toxicity: <code>pip install detoxify</code>. Place this node after your LLM node to validate outputs before Stop.
            </div>
          </>
        ) : (
          <>
          {isCustomTool && (
            <ToolVersionPicker
              toolId={data.toolId.replace('custom_', '')}
              value={data.config?.tool_version}
              readOnly={readOnly}
              onChange={(v) => {
                const { tool_version: _drop, ...rest } = data.config || {}
                onUpdate(activeNode.id, { config: v ? { ...rest, tool_version: v } : rest })
              }}
            />
          )}
          <ToolOptionFields
            toolId={data.toolId}
            config={data.config || {}}
            readOnly={readOnly}
            onChange={(patch) => onUpdate(activeNode.id, { config: { ...data.config, ...patch } })}
          />
          <ToolSecretFields
            toolId={data.toolId}
            toolLabel={data.label}
            config={data.config || {}}
            readOnly={readOnly}
            onChange={(patch) => onUpdate(activeNode.id, { config: { ...data.config, ...patch } })}
          />
          <div className="form-group">
            <label className="field-label">Tool Configuration (JSON)</label>
            <textarea rows={3} className="field-textarea code-font"
              value={JSON.stringify(displayConfig, null, 2)}
              disabled={readOnly}
              onChange={(e) => {
                try { onUpdate(activeNode.id, { config: JSON.parse(e.target.value) }) } catch { /* typing */ }
              }} />
          </div>
          </>
        )}

        {/* For every tool: what the model calls it with; for MCP servers, which of their tools */}
        {!isCustomTool && <ToolParametersInfo toolId={data.toolId} />}
        {data.toolType === 'mcp' && !getToolSpec(data.toolId)?.parameters && (
          <McpToolsPicker
            toolId={data.toolId}
            config={data.config || {}}
            readOnly={readOnly}
            onChange={(picked) => {
              const { mcp_tools: _drop, ...rest } = data.config || {}
              onUpdate(activeNode.id, { config: picked ? { ...rest, mcp_tools: picked } : rest })
            }}
          />
        )}
      </div>

      {/* 4. Node Actions */}
      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <div className="tool-status-box">
          <span className="status-dot online" />
          <span>Connected &amp; Available for Agents</span>
        </div>
        {isCustomTool && onEditCustomTool && (
          <button
            type="button"
            className="edit-code-btn"
            onClick={() => onEditCustomTool(data.toolId.replace('custom_', ''))}
            style={{ marginTop: 8 }}
          >
            ✏️ Edit Tool Code
          </button>
        )}
        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>
    </div>
  )
}
