import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { RunRating } from './RunRating'
import { DebugPauseCard } from './DebugPauseCard'
import type { DebugOverride, DebugPause } from './DebugPauseCard'
import { buildDebug } from '../utils/debugRun'
import { API_BASE } from '../types'
import { useCredentials } from '../context/CredentialsContext'
import { useExecution } from '../context/ExecutionContext'
import type {
  FlowNode, FlowEdge,
  LlmNodeData, ToolNodeData, ToolkitNodeData, MemoryNodeData, CacheNodeData,
  MasterAgentNodeData, ChildAgentNodeData, ConnectionNodeData,
  DocLoaderNodeData, TextSplitterNodeData, EmbeddingNodeData, VectorStoreNodeData, RetrieverNodeData,
  OutputParserNodeData, MiddlewareNodeData, HumanGateNodeData, CheckpointerNodeData, SyntheticDataNodeData,
} from '../types'
import type { Node } from '@xyflow/react'
import {
  type OutputFormat,
  FORMAT_OPTIONS,
  FORMAT_SUFFIXES,
  convertContent,
} from '../utils/contentFormats'
import { renderContent } from '../utils/renderMarkdown'
import { validatePipeline } from '../utils/pipelineValidation'
import { useRequiredConfig } from '../utils/toolCatalog'
import { DB_LOADER_TYPES } from '../utils/docLoaders'
import { useRunLogs, addRunLog, clearRunLogs, newRunId, logsToText } from '../utils/runLogs'
import type { RunLogLevel } from '../utils/runLogs'
import { RunLogList, TurnLogs } from './RunLogList'
import { useSubPipelineSummary } from '../hooks/useSubPipelineSummary'
import { retestConnection } from '../utils/connectionHealth'

interface Props {
  nodes: FlowNode[]
  edges: FlowEdge[]
  appId?: string
  appName?: string
  onUpdateNodeData?: (nodeId: string, fields: Record<string, any>) => void
  onFocusNode?: (nodeId: string) => void
  onConnectionsChanged?: () => void
}

// ── Conversation turn types ───────────────────────────────────────────────────

interface ToolCallEvent {
  name: string
  input: string
  output?: string
  nodeId?: string     // the canvas node that ran it (pins go there)
  stepKey?: string    // its checkpoint step, to read the full output for a pin
}

interface AgentStep {
  step: number
  agent: string
  role: string
  input: string
  output: string
  duration_ms: number
  attempt_count?: number
  used_fallback?: boolean
  effective_provider?: string
  effective_model?: string
  middleware_flags?: string[]
}

export interface RagSource {
  chunk_id?: string
  source: string
  content: string
  score?: number
  collection?: string
}

type TurnRole = 'user' | 'assistant' | 'agent_run'

// A master run paused at a human gate, waiting for a reviewer
interface PendingGate {
  key: string
  agent: string
  gate_type: 'approval' | 'edit' | 'review'
  label: string
  prompt_message: string
  output: string
  on_timeout: string
  expires_at: string | null
}

interface GateDecision {
  action: 'approve' | 'reject' | 'edit'
  edited_output?: string
  comment?: string
}

interface Turn {
  role: TurnRole
  content: string
  rawContent?: string        // original LLM output — never overwritten, used for re-conversion
  toolCalls: ToolCallEvent[]
  ragSources?: RagSource[]
  steps: number
  outputFormat?: OutputFormat
  // agent-run specific
  agentSteps?: AgentStep[]
  agentStrategy?: string
  agentGoal?: string
  agentRetrySteps?: number
  agentFallbackSteps?: number
  agentRunId?: string        // server run id — checkpointed, so the run can be resumed
  agentStatus?: 'completed' | 'paused' | 'failed' | 'rejected' | 'interrupted'
  pendingGate?: PendingGate
  agentResumedSteps?: number
  // LLM-run specific: checkpointed on the server under llmRunId, so a failed or cut-off run can resume
  llmRunId?: string
  llmStatus?: 'running' | 'completed' | 'failed' | 'interrupted' | 'paused'
  debugPause?: DebugPause   // stopped at a breakpoint: the step and the input it was about to use
  skillsLoaded?: { name: string; version?: number | null; tools: string[] }[]   // use_skill calls this run
  llmResumedSteps?: number
  meta?: {
    provider: string
    model: string
    usage?: Record<string, number>
    simulated?: boolean
    cache_hit?: boolean
    latency_ms?: number
    run_id?: string
    attempt_count?: number
    used_fallback?: boolean
    effective_provider?: string
    effective_model?: string
  }
  isStreaming?: boolean
  runId?: string             // links this turn to its entries in the run log store
}

// ── Helper: resolve connection node credentials into an MCP DB tool at runtime ─
// The tool node stores ONLY its identity (transport/read_only).
// Credentials and db_type come exclusively from the linked connection node at
// call time — they are NEVER saved in the tool node.

// Tool IDs that require a connection node (all DB-backed MCP tools)
const DB_MCP_TOOLS = new Set(['mcp_postgres', 'mcp_database'])

// Map connection_type → db_type that the backend understands
const CONN_TYPE_TO_DB: Record<string, string> = {
  postgres: 'postgres',
  postgresql: 'postgres',
  mysql: 'mysql',
  mariadb: 'mysql',
  sqlite: 'sqlite',
}

function mergeConnectionIntoTool(
  toolNode: FlowNode,
  nodes: FlowNode[],
  edges: FlowEdge[],
): ToolNodeData {
  const data = toolNode.data as ToolNodeData
  if (!DB_MCP_TOOLS.has(data.toolId)) return data

  // Find the connection node linked to this tool via any edge
  const linkedIds = edges
    .filter((e) => e.source === toolNode.id || e.target === toolNode.id)
    .map((e) => (e.source === toolNode.id ? e.target : e.source))

  const connNode = nodes.find(
    (n) => n.type === 'connection' && linkedIds.includes(n.id),
  ) as Node<ConnectionNodeData, 'connection'> | undefined

  if (!connNode) return data

  // Take credentials exclusively from the connection node
  const c = connNode.data.config || {}
  const dbType = CONN_TYPE_TO_DB[connNode.data.connection_type] ?? connNode.data.connection_type

  return {
    ...data,
    config: {
      // Tool identity only (no DSNs in args)
      transport: data.config?.transport ?? 'native',
      read_only: data.config?.read_only ?? true,
      // DB type — tells the backend which driver to use
      db_type: dbType,
      connection_type: connNode.data.connection_type,
      // Credentials from the connection node — runtime only, never persisted
      host: c.host,
      port: c.port,
      database: c.database,
      user: c.user,
      password: c.password,
    },
  }
}

// ── Helper: resolve child agents connected to a master via edges ──────────────

function getConnectedChildNodes(
  masterNodeId: string,
  nodes: FlowNode[],
  edges: FlowEdge[],
): Node<ChildAgentNodeData, 'child_agent'>[] {
  const connectedIds = edges
    .filter((e) => e.source === masterNodeId || e.target === masterNodeId)
    .map((e) => (e.source === masterNodeId ? e.target : e.source))

  return nodes.filter(
    (n) => n.type === 'child_agent' && connectedIds.includes(n.id),
  ) as Node<ChildAgentNodeData, 'child_agent'>[]
}

// ── Helper: tool, toolkit and skill nodes wired to a child agent ─────────────
// Same shape as an LLM node's attached_tools / attached_skills: the child runs the same tool loop.

function getChildAttachments(
  childNodeId: string,
  nodes: FlowNode[],
  edges: FlowEdge[],
): { tools: Record<string, unknown>[]; skills: Record<string, unknown>[] } {
  const connectedIds = edges
    .filter((e) => e.source === childNodeId || e.target === childNodeId)
    .map((e) => (e.source === childNodeId ? e.target : e.source))

  const tools = nodes
    .filter((n) => (n.type === 'tool' || n.type === 'toolkit') && connectedIds.includes(n.id))
    .map((n) => ({
      ...(n.type === 'tool' ? mergeConnectionIntoTool(n, nodes, edges) : (n.data as ToolkitNodeData)),
      nodeId: n.id,
    }))
  const skills = nodes
    .filter((n) => n.type === 'skill' && connectedIds.includes(n.id))
    .map((n) => n.data as any)
  return { tools, skills }
}

// ── Helper: middleware nodes connected to a node, as backend middleware_configs ─

function getMiddlewareConfigs(
  nodeId: string,
  nodes: FlowNode[],
  edges: FlowEdge[],
): { type: string; config: Record<string, any>; enabled: boolean }[] | undefined {
  const connectedIds = edges
    .filter((e) => e.source === nodeId || e.target === nodeId)
    .map((e) => (e.source === nodeId ? e.target : e.source))

  const configs = nodes
    .filter((n) => n.type === 'middleware' && connectedIds.includes(n.id))
    .map((n) => {
      const d = n.data as MiddlewareNodeData
      return { type: d.middleware_type, config: d.config ?? {}, enabled: d.enabled !== false }
    })
  return configs.length ? configs : undefined
}

// ── Helper: human_gate node connected to a node, as the backend's human_gate config ─

function getHumanGate(nodeId: string, nodes: FlowNode[], edges: FlowEdge[]) {
  const connectedIds = edges
    .filter((e) => e.source === nodeId || e.target === nodeId)
    .map((e) => (e.source === nodeId ? e.target : e.source))
  const gate = nodes.find((n) => n.type === 'human_gate' && connectedIds.includes(n.id))
  if (!gate) return undefined
  const d = gate.data as HumanGateNodeData
  return {
    gate_type: d.gate_type, label: d.label, prompt_message: d.prompt_message,
    timeout_hours: d.timeout_hours, on_timeout: d.on_timeout,
  }
}

/** The Checkpointer node wired to nodeId, else any on the canvas (it applies to the whole run). */
function getCheckpointConfig(nodeId: string, nodes: FlowNode[], edges: FlowEdge[]) {
  const connectedIds = edges
    .filter((e) => e.source === nodeId || e.target === nodeId)
    .map((e) => (e.source === nodeId ? e.target : e.source))
  const all = nodes.filter((n) => n.type === 'checkpointer')
  const node = all.find((n) => connectedIds.includes(n.id)) ?? all[0]
  if (!node) return undefined
  const d = node.data as CheckpointerNodeData
  return { save_steps: d.save_steps !== false, restore_on_resume: d.restore_on_resume !== false }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function PromptRunner({ nodes, edges, appId, appName, onUpdateNodeData, onFocusNode, onConnectionsChanged }: Props) {
  const { resolveApiKey } = useCredentials()
  const requiredConfig = useRequiredConfig()
  const [prompt, setPrompt] = useState('')
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const [history, setHistory] = useState<Turn[]>([])
  const [isRunning, setIsRunning] = useState(false)
  // Per-run drafts for the human-gate review card (edited output + comment)
  const [gateDrafts, setGateDrafts] = useState<Record<string, { edited: string; comment: string }>>({})
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'chat' | 'raw' | 'logs'>('chat')
  // Logs live in a global store (utils/runLogs) so the Operations → Logs tab sees every pipeline's runs.
  const allLogs = useRunLogs()
  const appLogs = useMemo(() => allLogs.filter((l) => l.appId === (appId ?? '')), [allLogs, appId])
  const runIdRef = useRef('')
  const addLog = useCallback((level: RunLogLevel, source: string, message: string) => {
    addRunLog({ level, source, message, runId: runIdRef.current, appId: appId ?? '', appName: appName ?? '' })
  }, [appId, appName])
  const [expandedSteps, setExpandedSteps] = useState<Record<string, boolean>>({})
  const [outputFormat, setOutputFormat] = useState<OutputFormat>('auto')
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null)
  const [ingestStatus, setIngestStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [ingestMsg, setIngestMsg] = useState<string>('')

  const abortRef = useRef<AbortController | null>(null)
  // Request body of each checkpointed LLM run (keys included, so kept in memory only): a resume
  // re-sends it unchanged, which the server checks before reusing the run's saved steps
  const llmRequestsRef = useRef<Record<string, Record<string, unknown>>>({})
  const bottomRef = useRef<HTMLDivElement>(null)
  // State of a workflow run paused on an Ask / Choice / Confirm step; the next prompt is its reply
  const wfStateRef = useRef<Record<string, any> | null>(null)

  // ── Detect what's on canvas ─────────────────────────────────────────────────
  const masterAgentNode = nodes.find((n) => n.type === 'master_agent') as
    | Node<MasterAgentNodeData, 'master_agent'>
    | undefined
  const primaryLlmNode = (nodes.find((n) => n.type === 'llm' && n.data.isSelected) ||
    nodes.find((n) => n.type === 'llm')) as
    | Node<LlmNodeData, 'llm'>
    | undefined
  const docLoaderNode = nodes.find((n) => n.type === 'doc_loader') as
    | Node<DocLoaderNodeData, 'doc_loader'>
    | undefined
  const splitterNode = nodes.find((n) => n.type === 'text_splitter') as
    | Node<TextSplitterNodeData, 'text_splitter'>
    | undefined
  const embeddingNode = nodes.find((n) => n.type === 'embedding') as
    | Node<EmbeddingNodeData, 'embedding'>
    | undefined
  const vectorStoreNode = nodes.find((n) => n.type === 'vector_store') as
    | Node<VectorStoreNodeData, 'vector_store'>
    | undefined
  const retrieverNode = nodes.find((n) => n.type === 'retriever') as
    | Node<RetrieverNodeData, 'retriever'>
    | undefined

  // Detect any output_parser node on canvas (used both here and in runLlmStream)
  const PARSER_TYPE_TO_FORMAT: Record<string, OutputFormat> = {
    json:     'json',
    pydantic: 'pydantic',
    csv:      'csv',
  }
  const canvasOutputParserNode = nodes.find((n) => n.type === 'output_parser') as
    | Node<OutputParserNodeData, 'output_parser'>
    | undefined
  const canvasParserFormat: OutputFormat | undefined = canvasOutputParserNode
    ? PARSER_TYPE_TO_FORMAT[(canvasOutputParserNode.data as OutputParserNodeData).parser_type]
    : undefined

  // Keep the outputFormat UI picker in sync with the canvas output_parser node.
  // Only auto-set when a parser node is present; never override a user's manual pick
  // once they have explicitly changed it (tracked by allowing the effect to run on node changes).
  useEffect(() => {
    if (canvasParserFormat) {
      setOutputFormat(canvasParserFormat)
    }
  }, [canvasParserFormat])

  // Show Ingest button when loader + vector store are both on canvas
  const canIngest = !!docLoaderNode && !!vectorStoreNode

  // Runner is usable if there's a master agent, workflow steps, OR an LLM node
  const isAgentMode = !!masterAgentNode
  // Workflow Step nodes drive the run; LLM nodes on the canvas are ignored by the workflow engine
  const isWorkflowMode = !isAgentMode && nodes.some((n) => n.type === 'wf_step')
  // No LLM of its own, only pipeline children (e.g. Start → Pipeline → Stop): the backend runs them in order
  const pipelineChildNodes = nodes.filter(
    (n) => n.type === 'child_agent' && (n.data as ChildAgentNodeData).kind === 'pipeline',
  )
  const isPipelineMode = !isAgentMode && !isWorkflowMode && !primaryLlmNode && pipelineChildNodes.length > 0
  const canRun = isAgentMode || isWorkflowMode || isPipelineMode || !!primaryLlmNode

  const toolCount = nodes.filter((n) => n.type === 'tool' || n.type === 'toolkit').length
  const hasMemory = nodes.some((n) => n.type === 'memory')
  const hasCache = nodes.some((n) => n.type === 'cache')

  // Include everything the called pipelines use (recursively, at their pinned versions)
  const subSummary = useSubPipelineSummary(nodes, appId)
  const subModels = subSummary?.models ?? []
  const subTools = subSummary?.tools ?? []
  const totalToolCount = toolCount + subTools.length
  const anyMemory = hasMemory || !!subSummary?.memory
  const anyCache = hasCache || !!subSummary?.cache
  const modelNames = [
    ...(primaryLlmNode ? [primaryLlmNode.data.model] : []),
    ...subModels.map((m) => m.model).filter((m) => m !== primaryLlmNode?.data.model),
  ]
  const modelTitle = [
    ...(primaryLlmNode ? [`${primaryLlmNode.data.model} — this pipeline`] : []),
    ...subModels.map((m) => `${m.model} (${m.provider}) — ${m.sources.join(', ')}`),
  ].join('\n')
  const toolTitle = [
    ...nodes.filter((n) => n.type === 'tool' || n.type === 'toolkit')
      .map((n) => `${String((n.data as Record<string, any>).label ?? n.type)} — this pipeline`),
    ...subTools.map((t) => `${t.name} — ${t.source}`),
  ].join('\n')
  const hasRagPipeline = !!(docLoaderNode || retrieverNode || vectorStoreNode)
  const childCount = isAgentMode
    ? getConnectedChildNodes(masterAgentNode!.id, nodes, edges).length
    : 0

  const validationIssues = useMemo(
    () => validatePipeline(nodes, edges, resolveApiKey, requiredConfig),
    [nodes, edges, resolveApiKey, requiredConfig],
  )
  const blockingIssues = validationIssues.filter((i) => i.severity === 'error')
  const isBlocked = canRun && blockingIssues.length > 0

  const [retestingNodeId, setRetestingNodeId] = useState<string | null>(null)
  const handleRetestConnection = useCallback(async (nodeId: string) => {
    const connNode = nodes.find((n) => n.id === nodeId && n.type === 'connection') as Node<ConnectionNodeData, 'connection'> | undefined
    if (!connNode?.data.connection_id) return
    setRetestingNodeId(nodeId)
    const health = await retestConnection(connNode.data.connection_id)
    onUpdateNodeData?.(nodeId, health)
    onConnectionsChanged?.()
    setRetestingNodeId(null)
  }, [nodes, onUpdateNodeData, onConnectionsChanged])

  const suggestedPrompts = useMemo(() => {
    // ── Per-tool prompt suggestions keyed by toolId ─────────────────────────
    const TOOL_PROMPTS: Record<string, string[]> = {
      weather:            ['What is the current weather in Tokyo?', 'Give me a 3-day forecast for New York City.', 'Compare today\'s weather in London vs Paris.'],
      web_search:         ['Search for the latest news on AI regulation in 2025.', 'Find the top 5 open-source LLM projects this month.', 'What are analysts saying about the semiconductor market this quarter?'],
      sql_database:       ['List the top 10 customers by total revenue this year.', 'Show me all orders placed in the last 7 days with their status.', 'Which products have inventory below the reorder threshold?'],
      python_interpreter: ['Write and run a Python script that generates a Fibonacci sequence up to 100.', 'Calculate the compound interest on $10,000 at 5% over 10 years.', 'Parse this CSV data and return the average of the third column.'],
      calculator:         ['What is the compound annual growth rate from $50,000 to $87,500 over 8 years?', 'Calculate the monthly payment on a $350,000 mortgage at 6.5% over 30 years.', 'What is 15% of 2,847 rounded to the nearest whole number?'],
      github_api:         ['Summarize the last 5 merged PRs in the openai/openai-python repo.', 'List all open issues labelled "bug" in vercel/next.js.', 'What is the most recently updated file in the main branch of torvalds/linux?'],
      email_sender:       ['Draft and send a follow-up email to the project stakeholders about the Q3 delivery milestone.', 'Send a brief status update email summarising today\'s completed tasks.', 'Compose and send a meeting invite confirmation for tomorrow at 2pm.'],
      slack_webhook:      ['Post a summary of today\'s AI news to the #general channel.', 'Send a deployment success notification to #engineering with the release version.', 'Alert the #ops channel that the nightly batch job has completed successfully.'],
      url_scraper:        ['Scrape https://news.ycombinator.com and summarise the top 5 stories.', 'Extract and summarise the key product features from https://openai.com/api.', 'Fetch the article at this URL and give me its main arguments in bullet points.'],
      file_reader:        ['Read the file at /tmp/report.txt and summarise its key findings.', 'Load the config file at /etc/app/settings.json and explain each setting.', 'Read the Python script at /src/main.py and explain what it does.'],
      csv_reader:         ['Read the CSV at /data/sales.csv and show the top 5 rows by revenue.', 'Load /data/users.csv and tell me how many records it contains and what columns are present.', 'Analyse /data/metrics.csv and identify any anomalies or outliers.'],
      shell_executor:     ['Run `df -h` and tell me which filesystem is running low on disk space.', 'Check running processes with `ps aux` and identify any high CPU consumers.', 'Run `ls -lh /var/log` and summarise the largest log files.'],
      s3_reader:          ['List all objects in the reports/ prefix of the S3 bucket.', 'Read the file latest-summary.json from S3 and extract the key metrics.', 'How many files are in the backups/ prefix and what is the total size?'],
      datetime_tool:      ['What is today\'s date and time in UTC, US/Eastern, and Asia/Tokyo?', 'How many days until December 31st?', 'What day of the week was January 1st, 2000?'],
      key_value_store:    ['Remember that my preferred language is French.', 'What do you have stored about me?', 'Forget my saved shipping address.'],
      json_transformer:   ['Extract the "name" and "email" fields from this JSON array.', 'Filter this JSON to only include records where status is "active".', 'Transform this nested JSON object into a flat structure.'],
      pdf_generator:      ['Write a one-page executive summary about the state of AI in healthcare and save it as a PDF.', 'Generate a PDF report with a title, 3 sections, and a conclusion on the provided topic.', 'Create a formatted PDF invoice for order #1234 with the line items below.'],
      text_summarizer:    ['Split this article into 500-character chunks with 50-character overlap and return the first three.', 'Chunk the following document and summarise each chunk in one sentence.', 'Break this text into paragraphs of roughly equal length.'],
      duckduckgo_search:  ['Search for the latest news on AI regulation.', 'Find the top 5 open-source LLM projects this month.', 'What are the best-reviewed mechanical keyboards right now?'],
      tavily_search:      ['What changed in the latest Python release? Cite sources.', 'Give me a sourced summary of this week\'s semiconductor news.', 'Who are the main competitors of Snowflake and how do they differ?'],
      brave_search:       ['Search for recent benchmarks comparing Postgres and MySQL.', 'Find privacy-focused alternatives to Google Analytics.', 'What are people saying about the newest MacBook?'],
      serper_search:      ['Google the current population of Tokyo.', 'Find the official documentation page for FastAPI background tasks.', 'Search Google for the latest quarterly earnings of NVIDIA.'],
      serpapi_search:     ['Google the opening hours of the Louvre.', 'Find the top results for "best vector database 2026".', 'Search for recent reviews of the Framework laptop.'],
      exa_search:         ['Find in-depth blog posts about building AI agents with tool use.', 'Find startups working on AI code review.', 'Find research-style articles on retrieval evaluation metrics.'],
      searxng_search:     ['Search for self-hosting guides for Nextcloud.', 'Find recent articles about Rust adoption at large companies.', 'Search for the release notes of the latest Kubernetes version.'],
      wolfram_alpha:      ['What is the integral of x^2 * sin(x)?', 'How far is the Moon from Earth right now?', 'What is the population density of Japan?'],
      stackoverflow_search: ['How do I handle exceptions in asyncio.gather?', 'Find answers on fixing CORS errors in FastAPI.', 'How do I deep-merge two dictionaries in Python?'],
      text_diff:          ['Compare these two versions of the paragraph and summarise what changed.', 'Diff the old and new config below and flag risky changes.', 'How similar are these two contract clauses?'],
      twilio_sms:         ['Text me a summary of today\'s calendar.', 'Send an SMS alert that the server CPU is above 90%.', 'Text the on-call engineer that the deploy failed.'],
      google_chat_webhook: ['Post the daily stand-up summary to Google Chat.', 'Notify the Google Chat space that the report is ready.', 'Send a Google Chat reminder about Friday\'s demo.'],
      ip_geolocation:     ['Where is the IP address 8.8.8.8 located?', 'Which ISP owns 1.1.1.1?', 'What timezone is the IP 151.101.1.69 in?'],
      crypto_price:       ['What are the current prices of Bitcoin and Ethereum?', 'How has Solana moved in the last 24 hours?', 'Compare BTC, ETH and DOGE prices in EUR.'],
      public_holidays:    ['List the public holidays in the US for 2026.', 'When is Easter Monday in GB this year?', 'Which public holidays does Germany have in December?'],
      unit_converter:     ['Convert 10 km to miles.', 'What is 72 F in Celsius?', 'How many MiB is 5 GB?'],
      dictionary:         ['What does "serendipity" mean? Give an example sentence.', 'Define "ephemeral" and list some synonyms.', 'How is "quinoa" pronounced?'],
      openlibrary_search: ['Find books by Ursula K. Le Guin and when they were first published.', 'Recommend classic books about the history of mathematics.', 'Which editions of "Dune" exist?'],
      pubmed_search:      ['Find recent clinical research on CRISPR treatments for sickle cell disease.', 'Summarise the latest PubMed papers on GLP-1 drugs and heart health.', 'What studies link sleep and memory consolidation?'],
      news_search:        ['What is the latest news about semiconductor export controls?', 'Summarise this week\'s top headlines about renewable energy.', 'What happened in the markets today?'],
      excel_reader:       ['Read /data/sales.xlsx and tell me which region has the highest revenue.', 'Summarise the second sheet of /data/budget.xlsx.', 'Find any negative values in /data/forecast.xlsx.'],
      docx_reader:        ['Read /docs/contract.docx and list every obligation for the supplier.', 'Summarise /docs/report.docx in five bullets.', 'Extract all tables from /docs/specs.docx.'],
      google_sheets_reader: ['Read this Google Sheet and tell me how many rows have status "Open".', 'Summarise the data in the sheet I shared.', 'Which column has missing values in this sheet?'],
      yaml_json_converter: ['Convert this docker-compose YAML to JSON.', 'Turn this JSON config into YAML.', 'Is this YAML valid? Show it as JSON.'],
      statistics_tool:    ['What are the mean, median and standard deviation of 12, 15, 18, 22, 30, 45?', 'Find the quartiles of these response times: 120, 98, 143, 87, 210, 99.', 'Is there an outlier in 5, 6, 5, 7, 6, 48?'],
      password_generator: ['Generate a 24-character password.', 'Create three strong passwords without symbols.', 'Make a random API token of 40 characters.'],
      json_schema_validator: ['Validate this JSON against the schema and list all errors.', 'Does this API response match the expected schema?', 'Which required fields are missing from this record?'],
      ntfy_push:          ['Send me a push notification when the report is ready.', 'Notify my phone that the deployment finished.', 'Push an urgent alert: the database CPU is above 95%.'],
      mattermost_webhook: ['Post today\'s stand-up summary to Mattermost.', 'Notify the Mattermost channel that the release is live.', 'Send the incident update to Mattermost.'],
      sendgrid_email:     ['Email the weekly summary to the team.', 'Send a welcome email to the new customer.', 'Email me the list of open support tickets.'],
      stock_quote:        ['What are Apple and Microsoft trading at right now?', 'How has NVDA moved over the last month?', 'Compare TSLA, F and GM prices today.'],
      geocode:            ['What are the coordinates of the Eiffel Tower?', 'What address is at 40.7484, -73.9857?', 'Where exactly is Machu Picchu?'],
      qr_code:            ['Make a QR code for https://example.com.', 'Create a QR code with our Wi-Fi network name.', 'Generate a QR code for my contact email.'],
      timezone_converter: ['What is 3pm PST in IST?', 'What time is it now in Tokyo?', 'Convert 9:30 Europe/Paris to New York time.'],
      air_quality:        ['How is the air quality in Delhi right now?', 'Is it safe to run outdoors in Beijing today?', 'Compare air quality in London and Paris.'],
      pdf_reader:         ['Read /docs/contract.pdf and list the termination clauses.', 'Summarise pages 1-3 of this PDF report.', 'What does the PDF at this URL say about pricing?'],
      html_to_markdown:   ['Convert https://example.com into clean markdown.', 'Turn this HTML email into readable text.', 'Extract the article text from this page as markdown.'],
      package_info:       ['What is the latest version of httpx and what does it depend on?', 'Compare the npm packages react and preact.', 'Which Python versions does pydantic support?'],
      openalex_search:    ['Find the most cited papers on retrieval-augmented generation.', 'List open-access papers on CRISPR published since 2023.', 'Who are the leading authors on graph neural networks?'],
      website_health_check: ['Is https://example.com up, and when does its TLS certificate expire?', 'Check our homepage and API status endpoints.', 'Does http://github.com redirect to HTTPS?'],
      dns_whois:          ['Who is the registrar for github.com and when does it expire?', 'Show the MX and TXT records for example.com.', 'Which nameservers does python.org use?'],
      date_calculator:    ['How many business days are there between today and 2026-12-24?', 'What date is 45 days after 2026-10-26?', 'What day of the week is December 25, 2026?'],
      jira:               ['Find open Jira bugs about checkout.', 'Summarise issue OPS-123 and its latest comments.', 'Create a Jira task to add retries to the payment webhook.'],
      confluence:         ['Search Confluence for the on-call runbook.', 'What does our Confluence page on deployment say about rollbacks?', 'Find onboarding docs in the Engineering space.'],
      notion:             ['Find our launch plan in Notion.', 'Read this Notion page and list the open to-dos.', 'Create a Notion page with today\'s meeting notes.'],
      zendesk:            ['Show recent Zendesk tickets about refunds.', 'Summarise ticket #512 and suggest a reply.', 'Create a Zendesk ticket for a customer who can\'t log in.'],
      pagerduty:          ['Trigger a PagerDuty incident: checkout error rate above 5%.', 'List open PagerDuty incidents.', 'Resolve the incident with dedup key dk-123.'],
      linear:             ['Find Linear issues about checkout performance.', 'Summarise ENG-123 and its latest comments.', 'Create a Linear issue to add retries to the payment webhook.'],
      hubspot:            ['Find the HubSpot contact for ada@example.com.', 'Which deals are closing this month?', 'Add jane@acme.com to HubSpot as a new contact.'],
      stripe:             ['Show recent payments for ada@example.com.', 'Does this customer have any unpaid invoices?', 'What is our current Stripe balance?'],
      slack:              ['Post the release notes for v2.1 to Slack.', 'Summarise the latest messages in the channel.', 'Reply in the deploy thread that the rollback is done.'],
      airtable:           ['Find customers marked VIP in Airtable.', 'List the first 10 records in the table.', 'Add a new record for Grace Hopper with status Active.'],
      trello:             ['Find Trello cards about the login bug.', 'What cards are in the backlog list?', 'Create a Trello card to update the onboarding docs.'],
      wikipedia:          ['Give me a short overview of the history of the Roman Empire.', 'Who was Ada Lovelace and why is she important?', 'Explain what a transformer neural network is, citing Wikipedia.'],
      arxiv_search:       ['Find the 5 most relevant recent papers on retrieval-augmented generation.', 'Summarise the latest arXiv research on LLM agents and tool use.', 'List recent papers on diffusion models for video generation.'],
      hacker_news:        ['What are the top stories on Hacker News right now?', 'Find recent Hacker News discussions about Rust in production.', 'Summarise what Hacker News is saying about the latest AI model releases.'],
      rss_reader:         ['Read https://hnrss.org/frontpage and summarise the top 5 items.', 'What are the latest posts on this RSS feed?', 'Check the feed and list any items published today.'],
      currency_converter: ['Convert 250 USD to EUR.', 'How much is 10,000 JPY in GBP today?', 'Convert 1,500 EUR into USD, CAD and AUD.'],
      discord_webhook:    ['Post a summary of today\'s AI news to our Discord channel.', 'Announce the new release v2.1 on Discord with the top 3 changes.', 'Send a reminder to Discord that the team sync starts in 15 minutes.'],
      teams_webhook:      ['Post the weekly status summary to the Teams channel.', 'Notify the Teams channel that the deployment to production succeeded.', 'Send an incident update to Teams: the API is degraded, investigating.'],
      telegram_bot:       ['Send me a Telegram message with today\'s top 3 headlines.', 'Message the Telegram chat that the nightly job has finished.', 'Send a Telegram alert with the current BTC price summary.'],
      regex_tool:         ['Extract every email address from the text below.', 'Find all dates in YYYY-MM-DD format in this log excerpt.', 'Replace all phone numbers in this text with [REDACTED].'],
      encode_hash:        ['Compute the SHA-256 hash of "hello world".', 'Base64-encode the string "api-user:secret".', 'Generate a new UUID for this record.'],
      docling:            ['Parse the attached document and extract all tables as JSON.', 'Read the PDF and list every section heading with its page number.', 'Summarise the document in 5 bullets, then list any action items mentioned.'],
      // MCP tools
      mcp_postgres:       ['List all tables in the connected database.', 'Show the last 10 rows from the orders table.', 'What is the average order value grouped by customer segment?'],
      mcp_database:       ['List all tables and their row counts.', 'Run a query to find duplicate records in the users table.', 'Show the schema for the products table.'],
    }

    // ── Agent mode ───────────────────────────────────────────────────────────
    if (isAgentMode) {
      return [
        'Research the latest trends in edge AI for 2026, then produce a concise executive brief with risks and recommendations.',
        'Create a launch plan for a B2B AI copilot in 90 days. Include milestones, owners, and top dependencies.',
        'Compare two architecture options for a customer-support agent platform and recommend one with rationale.',
      ]
    }

    // ── RAG pipeline ─────────────────────────────────────────────────────────
    if (hasRagPipeline) {
      const collectionName = (retrieverNode?.data as any)?.collection_name
        || (vectorStoreNode?.data as any)?.collection_name
        || 'the indexed documents'
      return [
        `Using ${collectionName}, answer: What are the key policies and their exceptions? Cite relevant chunks.`,
        `Summarize the content in ${collectionName} into 5 bullets, then list open questions for follow-up.`,
        `Find any conflicting statements in ${collectionName} and provide a reconciled answer with confidence notes.`,
      ]
    }

    // ── Tool-specific prompts ────────────────────────────────────────────────
    // Collect all tool IDs on canvas (tools + toolkits sub-tools)
    const canvasToolIds = nodes
      .filter((n) => n.type === 'tool' || n.type === 'toolkit')
      .flatMap((n) => {
        if (n.type === 'tool') return [(n.data as ToolNodeData).toolId]
        // toolkit: include the toolkit id and any sub-tool ids
        const tk = n.data as ToolkitNodeData
        return [tk.toolkitId, ...(tk.subTools ?? []).map((s: any) => s.toolId ?? s.id)]
      })

    if (canvasToolIds.length > 0) {
      // Pick suggestions from each tool in order, round-robin up to 3 total
      const suggestions: string[] = []
      let round = 0
      while (suggestions.length < 3) {
        let added = false
        for (const tid of canvasToolIds) {
          const pool = TOOL_PROMPTS[tid]
          if (pool && pool[round]) {
            suggestions.push(pool[round])
            if (suggestions.length >= 3) break
            added = true
          }
        }
        round++
        if (!added || round > 3) break
      }
      // Pad with generic tool prompts if we couldn't fill 3 slots
      const generic = [
        'Use available tools to gather evidence and provide a fact-checked answer with short citations.',
        'Analyze the request step by step. Call tools only when needed, then return a concise final response.',
        'Create an action-oriented summary with assumptions, risks, and next steps.',
      ]
      while (suggestions.length < 3) suggestions.push(generic[suggestions.length])
      return suggestions
    }

    // ── No tools / plain LLM ─────────────────────────────────────────────────
    return [
      'Summarize this incident report in 3 bullets.',
      'Draft a professional email response based on this context.',
      'Explain the topic in simple terms, then provide a deeper technical version.',
    ]
  }, [isAgentMode, hasRagPipeline, retrieverNode, vectorStoreNode, nodes])

  // ── AI-generated starter prompts (read from the live canvas, cached per pipeline) ──
  const aiPromptsKey = `pipesets:suggested-prompts:${appId ?? 'draft'}`
  const [aiPrompts, setAiPrompts] = useState<string[] | null>(null)
  const [generatingPrompts, setGeneratingPrompts] = useState(false)
  const [promptGenError, setPromptGenError] = useState<string | null>(null)

  useEffect(() => {
    setPromptGenError(null)
    try {
      const cached = localStorage.getItem(aiPromptsKey)
      setAiPrompts(cached ? JSON.parse(cached) : null)
    } catch {
      setAiPrompts(null)
    }
  }, [aiPromptsKey])

  const generatePrompts = useCallback(async () => {
    setGeneratingPrompts(true)
    setPromptGenError(null)
    try {
      const r = await fetch(`${API_BASE}/api/eval/suggest-prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          flow_data: { nodes, edges },
          app_id: appId ?? '',
          app_name: appName ?? '',
          provider_keys: {
            openai: resolveApiKey('openai'), anthropic: resolveApiKey('anthropic'),
            groq: resolveApiKey('groq'), gemini: resolveApiKey('gemini'), mistral: resolveApiKey('mistral'),
          },
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setPromptGenError(typeof d.detail === 'string' ? d.detail : r.statusText); return }
      const prompts: string[] = d.prompts ?? []
      if (prompts.length === 0) { setPromptGenError('The model returned no prompts.'); return }
      setAiPrompts(prompts)
      try { localStorage.setItem(aiPromptsKey, JSON.stringify(prompts)) } catch { /* storage unavailable */ }
    } catch (e) {
      setPromptGenError(e instanceof Error ? e.message : String(e))
    } finally {
      setGeneratingPrompts(false)
    }
  }, [nodes, edges, appId, appName, resolveApiKey, aiPromptsKey])

  const displayedPrompts = aiPrompts ?? suggestedPrompts

  const applySuggestedPrompt = useCallback((value: string) => {
    setPrompt(value)
    setError(null)
    promptRef.current?.focus()
  }, [])

  const connectedMemoryNode = nodes.find(
    (n) => n.type === 'memory' && (primaryLlmNode ? edges.some((e) => (e.source === primaryLlmNode.id && e.target === n.id) || (e.target === primaryLlmNode.id && e.source === n.id)) : true),
  ) as Node<MemoryNodeData, 'memory'> | undefined

  const activeSessionId = connectedMemoryNode?.data?.session_id

  // Auto-load history from SQLite when switching sessions or opening an app with existing memory
  useEffect(() => {
    if (!activeSessionId) return
    let isSubscribed = true
    fetch(`${API_BASE}/api/memory/${encodeURIComponent(activeSessionId)}?token_budget=50000`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!isSubscribed || !data || !Array.isArray(data.messages)) return
        // If history is empty and database has messages for this session, load them
        if (data.messages.length > 0) {
          const turns: Turn[] = data.messages.map((m: any) => ({
            role: m.role as 'user' | 'assistant',
            content: m.content,
            toolCalls: [],
            steps: 0,
            outputFormat: 'auto',
          }))
          setHistory(turns)
        }
      })
      .catch(() => {})
    return () => {
      isSubscribed = false
    }
  }, [activeSessionId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [history])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
    addLog('warn', 'run', 'Run stopped by user')
    setIsRunning(false)
    setHistory((prev) =>
      prev.map((t, i) =>
        i === prev.length - 1 && t.isStreaming
          ? { ...t, isStreaming: false, content: t.content + ' [stopped]' }
          : t,
      ),
    )
  }, [addLog])

  const handleClear = useCallback(() => {
    wfStateRef.current = null
    setHistory([])
    setError(null)
    setExpandedSteps({})
  }, [])

  const handleNewSession = useCallback(() => {
    const newSessionId = `session-node-${Date.now()}`
    if (connectedMemoryNode && onUpdateNodeData) {
      onUpdateNodeData(connectedMemoryNode.id, { session_id: newSessionId })
    }
    wfStateRef.current = null
    setHistory([])
    setError(null)
    setExpandedSteps({})
  }, [connectedMemoryNode, onUpdateNodeData])

  // ── LLM stream run (existing path) ─────────────────────────────────────────
  // ``resumeOf``: a failed / interrupted turn to continue from its checkpoint instead of a new run
  const runLlmStream = useCallback(async (userPrompt: string, resumeOf?: Turn,
    debugNext?: { override: DebugOverride | null; step: boolean }) => {
    if (!primaryLlmNode) return
    const saved = resumeOf?.llmRunId ? llmRequestsRef.current[resumeOf.llmRunId] : undefined
    if (resumeOf && !saved) { setError('This run was started before the page loaded, so it can only be resumed through the API.'); return }
    const llmRunId = resumeOf?.llmRunId ?? crypto.randomUUID()

    const connectedEdges = edges.filter(
      (e) => e.source === primaryLlmNode.id || e.target === primaryLlmNode.id,
    )
    const connectedIds = connectedEdges.map((e) =>
      e.source === primaryLlmNode.id ? e.target : e.source,
    )

    // Prefer the canvas-level output_parser node if it is wired to this LLM node;
    // fall back to the canvas-level node regardless of wiring, then the UI picker.
    const connectedOutputParserNode = nodes.find(
      (n) => n.type === 'output_parser' && connectedIds.includes(n.id),
    ) as Node<OutputParserNodeData, 'output_parser'> | undefined
    const activeParserNode = connectedOutputParserNode ?? canvasOutputParserNode
    const effectiveOutputFormat: OutputFormat =
      (activeParserNode
        ? PARSER_TYPE_TO_FORMAT[(activeParserNode.data as OutputParserNodeData).parser_type]
        : undefined) ?? outputFormat

    if (resumeOf) {
      // The server streams the whole answer again, saved part first
      setHistory((prev) => prev.map((t) => (t.llmRunId === llmRunId
        ? { ...t, content: '', rawContent: undefined, toolCalls: [], ragSources: undefined, isStreaming: true, llmStatus: 'running', debugPause: undefined, skillsLoaded: undefined }
        : t)))
    } else {
      const userTurn: Turn = { role: 'user', content: userPrompt, toolCalls: [], steps: 0 }
      const assistantTurn: Turn = {
        role: 'assistant', content: '', toolCalls: [], steps: 0,
        outputFormat: effectiveOutputFormat,
        isStreaming: true,
        runId: runIdRef.current,
        llmRunId,
        llmStatus: 'running',
      }
      setHistory((prev) => [...prev, userTurn, assistantTurn])
    }

    const attachedToolNodes = nodes
      .filter((n) => (n.type === 'tool' || n.type === 'toolkit') && connectedIds.includes(n.id))
      .map((n) => ({
        ...(n.type === 'tool'
          ? mergeConnectionIntoTool(n, nodes, edges)
          : (n.data as ToolkitNodeData)),
        nodeId: n.id,   // so the server can tell which node a tool call (and its pin / breakpoint) belongs to
      }))
    const attachedSkills = nodes
      .filter((n) => n.type === 'skill' && connectedIds.includes(n.id))
      .map((n) => n.data as any)

    const connectedMemoryNode = nodes.find(
      (n) => n.type === 'memory' && connectedIds.includes(n.id),
    ) as Node<MemoryNodeData, 'memory'> | undefined
    const connectedCacheNode = nodes.find(
      (n) => n.type === 'cache' && connectedIds.includes(n.id),
    ) as Node<CacheNodeData, 'cache'> | undefined
    const connectedSyntheticNodes = nodes
      .filter((n) => n.type === 'synthetic_data' && connectedIds.includes(n.id)) as Node<SyntheticDataNodeData, 'synthetic_data'>[]
    const nodeCfg = primaryLlmNode.data
    const memCfg = connectedMemoryNode?.data
    const cacheCfg = connectedCacheNode?.data

    // Append format instruction to system prompt
    const formatSuffix = FORMAT_SUFFIXES[effectiveOutputFormat]
    const effectiveSystemPrompt = (nodeCfg.system_prompt || '') + formatSuffix

    const retCfg = retrieverNode?.data
    // Resolve keys through the global credentials store, falling back to node-level keys
    const resolvedLlmKey = resolveApiKey(nodeCfg.provider, nodeCfg.api_key)
    const resolvedFallbackKey = nodeCfg.fallback_provider
      ? resolveApiKey(nodeCfg.fallback_provider, nodeCfg.fallback_api_key)
      : ''
    const resolvedEmbKey = retCfg
      ? resolveApiKey(retCfg.embedding_provider, retCfg.embedding_api_key)
      : ''
    let effectivePrompt = userPrompt
    if (!saved && connectedSyntheticNodes.length > 0) {
      const strictSyntheticRouting = connectedSyntheticNodes.some((n) => n.data.strict_routing === true)
      const promptLower = userPrompt.toLowerCase()
      const promptTokens = Array.from(new Set(
        promptLower.split(/[^a-z0-9_]+/g).map((t) => t.trim()).filter((t) => t.length >= 3),
      ))
      const ranked = connectedSyntheticNodes.map((syntheticNode) => {
        const synthetic = syntheticNode.data
        const datasetName = String(synthetic.dataset_name || '').toLowerCase()
        const nodeLabel = String(synthetic.label || '').toLowerCase()
        const columns = Array.isArray(synthetic.columns) ? synthetic.columns : []
        const colNames = columns.map((c) => String(c.name || '').toLowerCase()).filter(Boolean)
        let score = 0
        const matchedCols: string[] = []
        if (datasetName && promptLower.includes(datasetName)) score += 12
        if (nodeLabel && promptLower.includes(nodeLabel)) score += 8
        for (const col of colNames) {
          if (promptLower.includes(col)) {
            score += 8
            matchedCols.push(col)
          }
        }
        for (const tok of promptTokens) {
          if (datasetName.includes(tok)) score += 4
          if (nodeLabel.includes(tok)) score += 3
          for (const col of colNames) {
            if (col === tok) score += 6
            else if (col.includes(tok) || tok.includes(col)) score += 2
          }
        }
        return { syntheticNode, score, matchedCols: Array.from(new Set(matchedCols)) }
      }).sort((a, b) => b.score - a.score)
      const bestScore = ranked[0]?.score ?? 0
      const routeAll = !strictSyntheticRouting && bestScore <= 0
      const routed = strictSyntheticRouting
        ? ranked.slice(0, 1)
        : routeAll
          ? ranked
          : ranked.filter((r, i) => i === 0 || r.score >= bestScore - 2).slice(0, 3)
      addLog('info', 'synthetic', routeAll
        ? `Router: no clear dataset match, using all ${connectedSyntheticNodes.length} dataset(s)`
        : `Router: selected ${routed.length} dataset(s) (best score ${bestScore}${strictSyntheticRouting ? ', strict mode' : ''})`)
      routed.forEach((r) => {
        const dataset = r.syntheticNode.data.dataset_name || 'synthetic_dataset'
        const why = r.matchedCols.length ? `matched columns: ${r.matchedCols.join(', ')}` : `score: ${r.score}`
        addLog('info', 'synthetic', `Router -> ${dataset} (${why})`)
      })
      const datasetBlocks: string[] = []
      for (const { syntheticNode } of routed) {
        const synthetic = syntheticNode.data
        const datasetName = synthetic.dataset_name || 'synthetic_dataset'
        let rows = Array.isArray(synthetic.generated_preview_rows) ? synthetic.generated_preview_rows : []
        if (rows.length === 0) {
          const previewRows = Math.max(1, Math.min(20, synthetic.row_count || 10))
          addLog('info', 'synthetic', `Generating ${previewRows} preview row(s) from ${datasetName}`)
          try {
            const synthRes = await fetch(`${API_BASE}/api/eval/synthetic-preview`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                llm_config: {
                  provider: nodeCfg.provider,
                  model: nodeCfg.model,
                  api_key: resolvedLlmKey,
                  base_url: nodeCfg.base_url,
                  temperature: nodeCfg.temperature,
                  max_tokens: nodeCfg.max_tokens,
                  top_p: nodeCfg.top_p,
                },
                dataset_name: synthetic.dataset_name,
                row_count: synthetic.row_count,
                output_format: synthetic.output_format,
                schema_mode: synthetic.schema_mode,
                schema_json: synthetic.schema_json,
                columns: synthetic.columns,
                locale: synthetic.locale,
                seed: synthetic.seed,
                strict_schema: synthetic.strict_schema,
                include_edge_cases: synthetic.include_edge_cases,
                prompt_instructions: synthetic.prompt_instructions,
                test_prompt: userPrompt,
                preview_rows: previewRows,
              }),
            })
            const synthBody = await synthRes.json().catch(() => ({}))
            if (!synthRes.ok) {
              addLog('warn', 'synthetic', `Preview failed for ${datasetName}: ${String(synthBody?.detail || synthRes.statusText)}`)
            } else {
              rows = Array.isArray(synthBody.rows) ? synthBody.rows : []
            }
          } catch (e: any) {
            addLog('warn', 'synthetic', `Preview request failed for ${datasetName}: ${e?.message || String(e)}`)
          }
        } else {
          addLog('info', 'synthetic', `Using saved synthetic preview for ${datasetName} (${rows.length} row(s))`)
        }
        if (rows.length > 0) {
          const schemaSummary = synthetic.schema_mode === 'json'
            ? synthetic.schema_json
            : JSON.stringify((synthetic.columns || []).map((c) => ({ name: c.name, type: c.type })))
          datasetBlocks.push([
            `Dataset: ${datasetName}`,
            `Schema: ${schemaSummary}`,
            `Rows (JSON):`,
            JSON.stringify(rows.slice(0, 20), null, 2),
          ].join('\n'))
        }
      }
      if (datasetBlocks.length > 0) {
        effectivePrompt = [
          `Use the following synthetic datasets as context. Choose the dataset(s) whose columns match the user request.`,
          datasetBlocks.join('\n\n---\n\n'),
          '',
          `User request: ${userPrompt}`,
          `Return the requested result directly from the matching dataset rows. If SQL is requested explicitly, include SQL too.`,
        ].join('\n')
        addLog('info', 'synthetic', `Attached ${datasetBlocks.length} synthetic dataset(s) as run context`)
      } else {
        addLog('warn', 'synthetic', 'No synthetic rows available from connected datasets; running prompt without synthetic context')
      }
    }
    const request = saved ?? {
      prompt: effectivePrompt,
      app_id: appId,
      node_id: primaryLlmNode.id,
      config: {
        provider: nodeCfg.provider, model: nodeCfg.model,
        temperature: nodeCfg.temperature, max_tokens: nodeCfg.max_tokens,
        top_p: nodeCfg.top_p, api_key: resolvedLlmKey,
        system_prompt: effectiveSystemPrompt, base_url: nodeCfg.base_url,
        timeout_ms: nodeCfg.timeout_ms ?? 45000,
        max_retries: nodeCfg.max_retries ?? 1,
        retry_backoff_ms: nodeCfg.retry_backoff_ms ?? 500,
        fallback_provider: nodeCfg.fallback_provider || undefined,
        fallback_model: nodeCfg.fallback_model || undefined,
        fallback_api_key: resolvedFallbackKey || undefined,
        fallback_base_url: nodeCfg.fallback_base_url || undefined,
      },
      attached_tools: attachedToolNodes,
      attached_skills: attachedSkills,
      skill_mode: nodeCfg.skill_mode,
      max_active_skills: nodeCfg.max_active_skills,
      session_id: memCfg?.session_id,
      memory_config: memCfg
        ? {
            strategy: memCfg.strategy, token_budget: memCfg.token_budget, session_ttl_hours: memCfg.session_ttl_hours,
            long_term: !!memCfg.long_term, recall_k: memCfg.recall_k, extract: memCfg.extract_facts ?? true,
          }
        : undefined,
      cache_config: cacheCfg
        ? { scope: cacheCfg.scope, ttl_seconds: cacheCfg.ttl_seconds, max_size: cacheCfg.max_size }
        : undefined,
      middleware_configs: getMiddlewareConfigs(primaryLlmNode.id, nodes, edges),
      retriever_config: retCfg
        ? {
            node_id: retrieverNode?.id,
            collection_name: retCfg.collection_name,
            top_k: retCfg.top_k,
            score_threshold: retCfg.score_threshold,
            search_type: retCfg.search_type,
            rerank: retCfg.rerank,
            embedding_provider: retCfg.embedding_provider,
            embedding_model: retCfg.embedding_model,
            embedding_api_key: resolvedEmbKey,
          }
        : undefined,
      output_parser: activeParserNode
        ? {
            parser_type: (activeParserNode.data as OutputParserNodeData).parser_type,
            schema_json: (activeParserNode.data as OutputParserNodeData).schema_json,
            strict: (activeParserNode.data as OutputParserNodeData).strict,
          }
        : undefined,
      checkpoint: getCheckpointConfig(primaryLlmNode.id, nodes, edges),
    }
    llmRequestsRef.current[llmRunId] = request
    // A resume takes the Checkpointer node as it is now (e.g. switched to start over)
    // Breakpoints and pins as they are on the canvas now (they may change while a run is paused)
    const pausedStep = resumeOf?.debugPause?.step
    const debug = buildDebug([primaryLlmNode.id, ...connectedIds, ...(retrieverNode ? [retrieverNode.id] : [])], nodes, {
      step: debugNext?.step ?? false,
      overrides: pausedStep && debugNext?.override ? { [pausedStep]: debugNext.override } : undefined,
    })
    const body = JSON.stringify(resumeOf
      ? { ...request, checkpoint: getCheckpointConfig(primaryLlmNode.id, nodes, edges), resume_from: llmRunId, debug }
      : { ...request, run_id: llmRunId, debug })

    const abort = new AbortController()
    abortRef.current = abort

    const updateLast = (updater: (t: Turn) => Turn) =>
      setHistory((prev) => prev.map((t) => (t.llmRunId === llmRunId ? updater(t) : t)))

    const llmSrc = `llm:${nodeCfg.model}`
    let tokenCount = 0
    const toolStartedAt: Record<string, number> = {}
    const startedAt = Date.now()
    addLog('info', llmSrc, `Request sent to ${nodeCfg.provider}/${nodeCfg.model}` +
      (attachedToolNodes.length ? ` · ${attachedToolNodes.length} tool(s)` : '') +
      (memCfg ? ` · memory: ${memCfg.strategy}` : '') +
      (cacheCfg ? ` · cache: ${cacheCfg.scope}` : '') +
      (retCfg ? ` · retriever: ${retCfg.collection_name}` : ''))

    try {
      const res = await fetch(`${API_BASE}/api/run/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body, signal: abort.signal,
      })

      if (!res.ok || !res.body) {
        const errText = await res.text().catch(() => res.statusText)
        addLog('error', llmSrc, `HTTP ${res.status}: ${errText}`)
        setError(res.status === 429 && !/\[(Middleware|Guardrail)/.test(errText) ? `Budget exceeded: ${errText}` : `Server error: ${errText}`)
        // Never started (or refused to resume), so there's nothing on the server to resume
        updateLast((t) => ({ ...t, isStreaming: false, content: `Error: ${errText}`, llmStatus: undefined }))
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''

        for (const frame of frames) {
          const line = frame.trim()
          if (!line.startsWith('data: ')) continue
          let event: Record<string, any>
          try { event = JSON.parse(line.slice(6)) } catch { continue }

          switch (event.type) {
            case 'run':
              if (event.resumed_steps) addLog('info', llmSrc, `Resumed · reused ${event.resumed_steps} checkpointed step(s)`)
              updateLast((t) => ({ ...t, llmResumedSteps: event.resumed_steps as number }))
              break
            case 'token':
              if (tokenCount === 0) addLog('info', llmSrc, `First token after ${Date.now() - startedAt} ms`)
              tokenCount++
              updateLast((t) => ({ ...t, content: t.content + (event.text as string) }))
              break
            case 'thought':
              addLog('info', llmSrc, `Thought: ${String(event.text).slice(0, 200)}`)
              updateLast((t) => ({
                ...t,
                toolCalls: [...t.toolCalls, { name: '💭 Thought', input: event.text, output: undefined }],
              }))
              break
            case 'rag_sources':
              addLog('info', 'retriever', `Retrieved ${(event.sources as RagSource[])?.length ?? 0} source chunk(s)`)
              updateLast((t) => ({
                ...t,
                ragSources: event.sources as RagSource[],
              }))
              break
            case 'tool_call':
              // Step-by-step: highlight only the specific tool being called + LLM
              const calledTool = nodes.find((n) => {
                const label = (n.data as any).label?.toLowerCase() || ''
                const name = (n.data as any).name?.toLowerCase() || ''
                const target = (event.name as string).toLowerCase()
                return label === target || name === target || label.includes(target) || target.includes(label)
              })
              toolStartedAt[event.name as string] = Date.now()
              addLog('tool', `tool:${event.name}`, `Called with ${JSON.stringify(event.input ?? {}).slice(0, 200)}`)
              setExecutingNodeIds([primaryLlmNode.id, calledTool?.id].filter(Boolean) as string[])
              updateLast((t) => ({
                ...t,
                toolCalls: [...t.toolCalls, { name: event.name, input: event.input, output: undefined }],
              }))
              break
            case 'tool':
              addLog('tool', `tool:${event.name}`,
                `Returned${toolStartedAt[event.name as string] ? ` in ${Date.now() - toolStartedAt[event.name as string]} ms` : ''}: ${String(typeof event.output === 'string' ? event.output : JSON.stringify(event.output ?? '')).slice(0, 200)}`)
              updateLast((t) => {
                const calls = [...t.toolCalls]
                const lastPending = calls
                  .map((c, i) => ({ c, i }))
                  .reverse()
                  .find(({ c }) => c.output === undefined && c.name === event.name)
                if (lastPending) calls[lastPending.i] = { ...calls[lastPending.i], output: event.output,
                  nodeId: event.node_id ?? undefined, stepKey: event.step_key ?? undefined }
                return { ...t, toolCalls: calls }
              })
              // Tool finished: return execution focus back to LLM
              setExecutingNodeIds([primaryLlmNode.id])
              break
            case 'trace':
              // Server-side timing of each finished call; tool calls are already timed above
              if (event.span === 'llm') addLog('info', llmSrc, `Model call (step ${event.step}) took ${event.duration_ms} ms`)
              break
            case 'skill_loaded':
              addLog('info', llmSrc, `Loaded skill “${event.name}”${event.version ? ` v${event.version}` : ''}` +
                (event.tools?.length ? ` · tools on: ${(event.tools as string[]).join(', ')}` : ''))
              updateLast((t) => ({ ...t, skillsLoaded: [...(t.skillsLoaded ?? []),
                { name: event.name as string, version: event.version as number | null, tools: (event.tools ?? []) as string[] }] }))
              break
            case 'debug_paused':
              addLog('warn', llmSrc, `Paused at a breakpoint before ${event.kind} “${event.label}” (${event.step})`)
              updateLast((t) => ({ ...t, llmStatus: 'paused', debugPause: event as unknown as DebugPause }))
              if (event.node_id) onFocusNode?.(event.node_id as string)
              break
            case 'step':
              addLog('info', llmSrc, `Step ${event.step}`)
              updateLast((t) => ({ ...t, steps: event.step as number }))
              break
            case 'meta':
              addLog(event.used_fallback ? 'warn' : 'info', llmSrc,
                `Meta: ${event.effective_provider ?? event.provider}/${event.effective_model ?? event.model}` +
                (event.latency_ms != null ? ` · ${event.latency_ms} ms` : '') +
                (event.usage ? ` · usage ${JSON.stringify(event.usage)}` : '') +
                (event.cache_hit ? ' · cache hit' : '') +
                (event.used_fallback ? ' · fallback used' : '') +
                (event.attempt_count > 1 ? ` · ${event.attempt_count} attempts` : ''))
              updateLast((t) => ({
                ...t,
                meta: {
                  provider: event.provider, model: event.model,
                  usage: event.usage, simulated: event.simulated, cache_hit: event.cache_hit,
                    latency_ms: event.latency_ms, run_id: event.run_id,
                    attempt_count: event.attempt_count,
                    used_fallback: event.used_fallback,
                    effective_provider: event.effective_provider,
                    effective_model: event.effective_model,
                },
              }))
              break
            case 'error':
              addLog('error', llmSrc, String(event.message))
              setError(event.message as string)
              // retract: a response guardrail blocked output that already streamed — replace it
              updateLast((t) => event.retract
                ? { ...t, content: `⚠ ${event.message}`, rawContent: undefined, isStreaming: false, llmStatus: 'failed' }
                : { ...t, content: t.content || `⚠ ${event.message}`, isStreaming: false, llmStatus: 'failed' })
              break
            case 'done':
              addLog('ok', llmSrc, `Done · ${tokenCount} token event(s) in ${Date.now() - startedAt} ms`)
              // Save rawContent on completion so reformat can always use the original.
              // If the Output Parser node drove a specific format, apply post-processing now.
              updateLast((t) => {
                const raw = t.rawContent ?? t.content
                const converted = effectiveOutputFormat !== 'auto'
                  ? convertContent(raw, effectiveOutputFormat)
                  : raw
                return { ...t, isStreaming: false, rawContent: raw, content: converted,
                  llmStatus: t.llmStatus === 'running' ? 'completed' : t.llmStatus }
              })
              break
          }
        }
      }
    } catch (e: any) {
      // Stopped or cut off mid-run: the server keeps the finished steps, so the run can resume
      if (e.name === 'AbortError') {
        updateLast((t) => ({ ...t, isStreaming: false, llmStatus: t.llmStatus === 'running' ? 'interrupted' : t.llmStatus }))
      } else {
        addLog('error', llmSrc, `Backend not reachable: ${e.message}`)
        const nodeCfgFallback = primaryLlmNode.data
        updateLast((t) => ({
          ...t,
          content: t.content || `[Offline Mode — ${nodeCfgFallback.model}]\n\nBackend not running.\n\nYour prompt: "${userPrompt}"`,
          isStreaming: false,
          // Resumable once the server announced the run
          llmStatus: t.llmResumedSteps !== undefined ? 'interrupted' : undefined,
        }))
      }
    }
  }, [nodes, edges, primaryLlmNode, retrieverNode, addLog, onFocusNode])

  const resumeLlmRun = useCallback(async (turn: Turn) => {
    const saved = turn.llmRunId ? llmRequestsRef.current[turn.llmRunId] : undefined
    setError(null)
    setIsRunning(true)
    addLog('info', 'run', `Resuming run ${turn.llmRunId?.slice(0, 8)} from its checkpoint`)
    try {
      await runLlmStream(String(saved?.prompt ?? ''), turn)
    } finally {
      setIsRunning(false)
    }
  }, [runLlmStream, addLog])

  // Paused at a breakpoint: continue (to the next one) or step, with the paused step's edited input
  const continueDebug = useCallback(async (turn: Turn, override: DebugOverride | null, step: boolean) => {
    const saved = turn.llmRunId ? llmRequestsRef.current[turn.llmRunId] : undefined
    setError(null)
    setIsRunning(true)
    addLog('info', 'run', `${step ? 'Stepping' : 'Continuing'} run ${turn.llmRunId?.slice(0, 8)}${override ? ' with an edited input' : ''}`)
    try {
      await runLlmStream(String(saved?.prompt ?? ''), turn, { override, step })
    } finally {
      setIsRunning(false)
    }
  }, [runLlmStream, addLog])

  const stopDebug = useCallback(async (turn: Turn) => {
    if (!turn.llmRunId) return
    await fetch(`${API_BASE}/api/agents/runs/${encodeURIComponent(turn.llmRunId)}/cancel`, { method: 'POST' }).catch(() => null)
    setHistory((prev) => prev.map((t) => (t.llmRunId === turn.llmRunId
      ? { ...t, llmStatus: undefined, debugPause: undefined, content: t.content || '■ Stopped at a breakpoint.' }
      : t)))
  }, [])

  // 📌 Pin an output to its node, so later runs use it instead of running the node
  const pinOutput = useCallback(async (nodeId: string, output: string, runId?: string, stepKey?: string) => {
    if (!onUpdateNodeData) return
    let full = output
    if (runId && stepKey) {   // streamed outputs are previews: pin what the step really returned
      const r = await fetch(`${API_BASE}/api/agents/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepKey)}`).catch(() => null)
      if (r?.ok) full = (await r.json()).output ?? output
    }
    onUpdateNodeData(nodeId, { debug_pin: { output: full, pinned_at: new Date().toISOString() } })
    addLog('ok', 'debug', `Pinned an output to “${(nodes.find((n) => n.id === nodeId)?.data as any)?.label ?? nodeId}”`)
  }, [onUpdateNodeData, addLog, nodes])

  // Request body for a master run, rebuilt from the canvas on every start and resume
  // (keys come from the browser and are never stored with the run's checkpoint).
  const buildAgentRequest = useCallback((goal: string) => {
    if (!masterAgentNode) return null
    const masterData = masterAgentNode.data

    // Collect child agents connected to this master via edges
    const connectedChildren = getConnectedChildNodes(masterAgentNode.id, nodes, edges)

    // For each child, auto-resolve tool ids from its own edges
    const childConfigs = connectedChildren.map((childNode) => {
      const cd = childNode.data
      const attached = getChildAttachments(childNode.id, nodes, edges)
      return {
        agent_id: childNode.id,
        label: cd.label,
        role: cd.role,
        provider: cd.provider,
        model: cd.model,
        api_key: cd.kind === 'external' ? cd.api_key : resolveApiKey(cd.provider, cd.api_key),
        timeout_ms: cd.timeout_ms ?? 45000,
        max_retries: cd.max_retries ?? 1,
        retry_backoff_ms: cd.retry_backoff_ms ?? 500,
        fallback_provider: cd.fallback_provider || undefined,
        fallback_model: cd.fallback_model || undefined,
        fallback_api_key: cd.fallback_api_key || undefined,
        fallback_base_url: cd.fallback_base_url || undefined,
        base_url: cd.base_url || undefined,
        system_prompt: cd.system_prompt,
        attached_tools: attached.tools,
        attached_skills: attached.skills,
        // Older flows listed tool ids on the node; the server uses them only when no tool node is wired
        allowed_tool_ids: cd.allowed_tool_ids ?? [],
        skill_ids: cd.skill_ids ?? [],
        kind: cd.kind ?? 'llm',
        app_id: cd.app_id || '',
        app_version: cd.app_version ?? 0,
        endpoint_url: cd.endpoint_url || '',
        protocol: cd.protocol ?? 'openai',
        auth_type: cd.auth_type ?? 'bearer',
        auth_header: cd.auth_header || 'X-API-Key',
        request_template: cd.request_template || '',
        response_path: cd.response_path || '',
        middleware_configs: getMiddlewareConfigs(childNode.id, nodes, edges),
        human_gate: getHumanGate(childNode.id, nodes, edges),
        pinned_output: cd.debug_pin?.output,   // editor debugging: use it instead of running the child
      }
    })

    return {
      goal,
      provider: masterData.provider,
      model: masterData.model,
      api_key: resolveApiKey(masterData.provider, masterData.api_key),
      timeout_ms: masterData.timeout_ms ?? 45000,
      max_retries: masterData.max_retries ?? 1,
      retry_backoff_ms: masterData.retry_backoff_ms ?? 500,
      fallback_provider: masterData.fallback_provider || undefined,
      fallback_model: masterData.fallback_model || undefined,
      fallback_api_key: masterData.fallback_api_key || undefined,
      fallback_base_url: masterData.fallback_base_url || undefined,
      base_url: masterData.base_url || undefined,
      strategy: masterData.strategy,
      max_steps: masterData.max_steps,
      children: childConfigs,
      middleware_configs: getMiddlewareConfigs(masterAgentNode.id, nodes, edges),
      human_gate: getHumanGate(masterAgentNode.id, nodes, edges),
      checkpoint: getCheckpointConfig(masterAgentNode.id, nodes, edges),
      // Global key store, so pipeline children can resolve keys their saved flow doesn't contain
      provider_keys: {
        openai: resolveApiKey('openai'), anthropic: resolveApiKey('anthropic'),
        groq: resolveApiKey('groq'), gemini: resolveApiKey('gemini'), mistral: resolveApiKey('mistral'),
      },
    }
  }, [masterAgentNode, nodes, edges, resolveApiKey])

  // POST a master run (new or resume) and fold the result into the turn for that run id.
  const sendAgentRequest = useCallback(async (agentRunId: string, body: Record<string, unknown>) => {
    const updateRun = (updater: (t: Turn) => Turn) =>
      setHistory((prev) => prev.map((t) => (t.agentRunId === agentRunId ? updater(t) : t)))
    const isResume = Boolean(body.resume_from)

    const abort = new AbortController()
    abortRef.current = abort
    const agentStartedAt = Date.now()

    try {
      const res = await fetch(`${API_BASE}/api/agents/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abort.signal,
        body: JSON.stringify(body),
      })

      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText)
        addLog('error', 'master', `HTTP ${res.status}: ${errText}`)
        setError(res.status === 429 && !/\[(Middleware|Guardrail)/.test(errText) ? `Budget exceeded: ${errText}` : `Agent run error: ${errText}`)
        if (!isResume) {
          updateRun((t) => ({ ...t, isStreaming: false, content: `Error: ${errText}` }))
          return
        }
        // A refused resume (flow changed, already resumed, still waiting for review…):
        // reload the run's real state so the turn matches the server again.
        const runRes = await fetch(`${API_BASE}/api/agents/runs/${encodeURIComponent(agentRunId)}`).catch(() => null)
        const run = runRes?.ok ? await runRes.json() : null
        updateRun((t) => (run ? {
          ...t,
          isStreaming: false,
          agentStatus: run.status === 'running' ? 'interrupted' : run.status,
          pendingGate: run.pending_gate ?? undefined,
          agentSteps: run.steps ?? t.agentSteps,
          steps: (run.steps ?? []).length,
          content: run.final_answer || t.content,
        } : { ...t, isStreaming: false }))
        return
      }

      const data = await res.json()
      const freshSteps: AgentStep[] = (data.steps ?? []).slice(data.resumed_steps ?? 0)
      freshSteps.forEach((s: AgentStep) => {
        const extras = [
          s.effective_model ? `${s.effective_provider ?? ''}/${s.effective_model}` : '',
          s.attempt_count && s.attempt_count > 1 ? `${s.attempt_count} attempts` : '',
          s.used_fallback ? 'fallback used' : '',
        ].filter(Boolean).join(' · ')
        addLog(s.used_fallback ? 'warn' : 'info', `agent:${s.agent}`,
          `Step ${s.step} (${s.role}) finished in ${s.duration_ms} ms${extras ? ` · ${extras}` : ''}`)
        ;(s.middleware_flags ?? []).forEach((f) => addLog('warn', `agent:${s.agent}`, f))
      })
      if (data.resumed_steps) addLog('info', 'master', `Resumed · reused ${data.resumed_steps} checkpointed step(s)`)
      if (data.error) addLog('error', 'master', String(data.error))
      if (data.status === 'paused') {
        addLog('warn', 'master', `Paused for human review at ${data.pending_gate?.agent ?? 'a gate'}`)
      } else {
        addLog(data.status === 'completed' ? 'ok' : 'error', 'master',
          `Run ${data.status} · ${data.total_steps ?? 0} step(s) in ${Date.now() - agentStartedAt} ms` +
          (data.retry_steps ? ` · ${data.retry_steps} retry` : '') + (data.fallback_steps ? ` · ${data.fallback_steps} fallback` : ''))
      }

      updateRun((t) => ({
        ...t,
        isStreaming: false,
        content: data.final_answer ?? '',
        agentSteps: data.steps ?? [],
        steps: data.total_steps ?? 0,
        agentRetrySteps: data.retry_steps ?? 0,
        agentFallbackSteps: data.fallback_steps ?? 0,
        agentStatus: data.status,
        pendingGate: data.pending_gate ?? undefined,
        agentResumedSteps: data.resumed_steps ?? 0,
        meta: {
          provider: String(body.provider),
          model: String(body.model),
        },
      }))
    } catch (e: any) {
      if (e.name !== 'AbortError') {
        // The run keeps its checkpoint server-side; once the backend is back it can resume.
        addLog('error', 'master', `Backend not reachable: ${e.message}`)
        updateRun((t) => ({
          ...t,
          isStreaming: false,
          agentStatus: 'interrupted',
          content: t.content || `[Agent run interrupted — backend not reachable]\n\nGoal: "${t.agentGoal ?? ''}"`,
        }))
      }
    }
  }, [addLog])

  // ── Agent run (new path) ────────────────────────────────────────────────────
  const runAgentFlow = useCallback(async (userPrompt: string) => {
    const body = buildAgentRequest(userPrompt)
    if (!body || !masterAgentNode) return
    const agentRunId = crypto.randomUUID()

    // Add user + placeholder agent_run turn
    const userTurn: Turn = { role: 'user', content: userPrompt, toolCalls: [], steps: 0 }
    const agentTurn: Turn = {
      role: 'agent_run',
      content: '',
      toolCalls: [],
      steps: 0,
      agentSteps: [],
      agentStrategy: body.strategy,
      agentGoal: userPrompt,
      agentRunId,
      isStreaming: true,
      runId: runIdRef.current,
    }
    setHistory((prev) => [...prev, userTurn, agentTurn])

    addLog('info', 'master', `Goal sent · strategy ${body.strategy} · ${body.children.length} child agent(s) · max ${body.max_steps} steps`)
    body.children.forEach((c) => addLog('info', 'master', `Child: ${c.label} (${c.role}) · ${c.kind} · ${c.provider}/${c.model} · ${c.attached_tools.length || (c.allowed_tool_ids?.length ?? 0)} tool(s)` +
      (c.human_gate ? ` · ✋ ${c.human_gate.gate_type} gate` : '')))

    await sendAgentRequest(agentRunId, { ...body, run_id: agentRunId })
  }, [masterAgentNode, buildAgentRequest, sendAgentRequest, addLog])

  // Continue a paused / interrupted / failed run from its checkpoint.
  const resumeAgentRun = useCallback(async (turn: Turn, decision?: GateDecision) => {
    if (!turn.agentRunId || !turn.agentGoal) return
    const body = buildAgentRequest(turn.agentGoal)
    if (!body) { setError('Add the Master Agent back to the canvas to resume this run.'); return }
    const agentRunId = turn.agentRunId
    setError(null)
    setIsRunning(true)
    setHistory((prev) => prev.map((t) => (t.agentRunId === agentRunId ? { ...t, isStreaming: true, pendingGate: undefined } : t)))
    addLog('info', 'master', decision
      ? `Gate decision: ${decision.action}${decision.comment ? ` — ${decision.comment}` : ''} · resuming`
      : `Resuming run ${agentRunId.slice(0, 8)} from its checkpoint`)
    try {
      await sendAgentRequest(agentRunId, { ...body, resume_from: agentRunId, gate_decision: decision })
    } finally {
      setIsRunning(false)
    }
  }, [buildAgentRequest, sendAgentRequest, addLog])

  // ── Workflow run (Ask / Choice / Confirm / Tool Call / Message steps) ───────
  // Uses the stateless preview endpoint so the unsaved canvas runs without publishing.
  const runWorkflow = useCallback(async (userPrompt: string) => {
    const waiting = wfStateRef.current
    setHistory((prev) => [
      ...prev,
      { role: 'user', content: userPrompt, toolCalls: [], steps: 0 },
      { role: 'assistant', content: '', toolCalls: [], steps: 0, isStreaming: true, runId: runIdRef.current },
    ])
    const updateLast = (updater: (t: Turn) => Turn) =>
      setHistory((prev) => prev.map((t, i) => (i === prev.length - 1 ? updater(t) : t)))
    addLog('info', 'workflow', waiting ? `Reply sent to step ${waiting.current_node}` : 'Workflow started')

    const abort = new AbortController()
    abortRef.current = abort
    try {
      const res = await fetch(`${API_BASE}/api/workflows/preview`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ flow: { nodes, edges }, state: waiting, message: userPrompt }),
        signal: abort.signal,
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) {
        const msg = typeof d.detail === 'string' ? d.detail : res.statusText
        wfStateRef.current = null
        addLog('error', 'workflow', `HTTP ${res.status}: ${msg}`)
        setError(`Workflow error: ${msg}`)
        updateLast((t) => ({ ...t, isStreaming: false, content: `Error: ${msg}` }))
        return
      }

      wfStateRef.current = d.status === 'waiting_input' ? d.state : null
      const options: { label: string }[] = d.input?.options ?? []
      const parts: string[] = [...(d.messages ?? [])]
      if (options.length) parts.push(options.map((o, i) => `${i + 1}. ${o.label}`).join('\n'))
      if (d.status === 'completed') parts.push('✅ Workflow completed.')
      const content = parts.join('\n\n')
      updateLast((t) => ({ ...t, isStreaming: false, content, rawContent: content }))
      addLog(d.status === 'failed' ? 'error' : 'info', 'workflow',
        d.status === 'waiting_input' ? `Waiting for reply (${d.input?.variable})` : `Workflow ${d.status}`)
      if (d.status === 'failed') setError(d.error)
    } catch (e: any) {
      if (e?.name === 'AbortError') return
      wfStateRef.current = null
      addLog('error', 'workflow', `Network error: ${e?.message}`)
      updateLast((t) => ({ ...t, isStreaming: false, content: '[Workflow failed — backend not reachable]' }))
    }
  }, [nodes, edges, addLog])

  const { setExecutingNodeIds } = useExecution()

  // ── Pipeline-only run (canvas just delegates to published pipelines) ────────
  const runPipelineFlow = useCallback(async (userPrompt: string) => {
    setHistory((prev) => [
      ...prev,
      { role: 'user', content: userPrompt, toolCalls: [], steps: 0 },
      { role: 'assistant', content: '', toolCalls: [], steps: 0, isStreaming: true, runId: runIdRef.current },
    ])
    const updateLast = (updater: (t: Turn) => Turn) =>
      setHistory((prev) => prev.map((t, i) => (i === prev.length - 1 ? updater(t) : t)))
    setExecutingNodeIds(pipelineChildNodes.map((n) => n.id))
    addLog('info', 'pipeline', `Calling ${pipelineChildNodes.map((n) => {
      const d = n.data as ChildAgentNodeData
      return `${d.app_name || d.label} v${d.app_version || 'latest'}`
    }).join(' → ')}`)

    const abort = new AbortController()
    abortRef.current = abort
    try {
      const res = await fetch(`${API_BASE}/api/pipelines/run-flow`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: userPrompt,
          app_id: appId ?? '',
          flow_data: { nodes, edges },
          provider_keys: {
            openai: resolveApiKey('openai'), anthropic: resolveApiKey('anthropic'),
            groq: resolveApiKey('groq'), gemini: resolveApiKey('gemini'), mistral: resolveApiKey('mistral'),
          },
        }),
        signal: abort.signal,
      })
      const d = await res.json().catch(() => ({}))
      if (!res.ok) {
        const msg = typeof d.detail === 'string' ? d.detail : res.statusText
        addLog('error', 'pipeline', `HTTP ${res.status}: ${msg}`)
        setError(`Pipeline error: ${msg}`)
        updateLast((t) => ({ ...t, isStreaming: false, content: `Error: ${msg}` }))
        return
      }
      const content = String(d.output ?? '')
      updateLast((t) => ({ ...t, isStreaming: false, content, rawContent: content }))
      addLog(d.ok ? 'info' : 'error', 'pipeline', d.ok ? `Done in ${d.latency_ms} ms (${d.model})` : String(d.error))
      if (!d.ok) setError(String(d.error))
    } catch (e: any) {
      if (e?.name === 'AbortError') return
      addLog('error', 'pipeline', `Network error: ${e?.message}`)
      updateLast((t) => ({ ...t, isStreaming: false, content: '[Pipeline failed — backend not reachable]' }))
    }
  }, [nodes, edges, appId, pipelineChildNodes, resolveApiKey, addLog, setExecutingNodeIds])

  // ── Unified run handler ─────────────────────────────────────────────────────

  const onRun = useCallback(async () => {
    runIdRef.current = newRunId()
    if (blockingIssues.length > 0) {
      setError(`Run blocked: ${blockingIssues.length} validation issue(s) must be fixed first.`)
      addLog('error', 'run', `Run blocked: ${blockingIssues.length} validation issue(s)`)
      return
    }
    if (!canRun) {
      setError('Add an LLM, Master Agent or Pipeline node to the canvas first.')
      addLog('error', 'run', 'Run blocked: no LLM or Master Agent node on the canvas')
      return
    }
    if (!prompt.trim()) { setError('Please type a prompt first.'); return }

    setError(null)
    setIsRunning(true)
    const currentPrompt = prompt
    addLog('info', 'run', `── Run started (${isAgentMode ? 'agent' : isWorkflowMode ? 'workflow' : isPipelineMode ? 'pipeline' : 'llm'} mode): "${currentPrompt.slice(0, 80)}${currentPrompt.length > 80 ? '…' : ''}"`)
    setPrompt('')

    // 1. Initial execution step: Start -> LLM (+ Memory if connected)
    const startNode = nodes.find((n) => n.type === 'start')
    const memNode = nodes.find((n) => n.type === 'memory')
    const initialActive = [primaryLlmNode?.id, startNode?.id, memNode?.id].filter(Boolean) as string[]
    setExecutingNodeIds(initialActive)

    try {
      if (isAgentMode) {
        await runAgentFlow(currentPrompt)
      } else if (isWorkflowMode) {
        await runWorkflow(currentPrompt)
      } else if (isPipelineMode) {
        await runPipelineFlow(currentPrompt)
      } else {
        await runLlmStream(currentPrompt)
      }
    } finally {
      // Final step: light up Stop node briefly then clear
      const stopNode = nodes.find((n) => n.type === 'stop')
      if (stopNode) {
        setExecutingNodeIds([stopNode.id])
        await new Promise((r) => setTimeout(r, 600))
      }
      setIsRunning(false)
      setExecutingNodeIds([])
    }
  }, [blockingIssues.length, canRun, isAgentMode, isWorkflowMode, isPipelineMode, prompt, runAgentFlow, runWorkflow, runPipelineFlow, runLlmStream, nodes, setExecutingNodeIds, addLog])

  // ── Ingest pipeline (PDF Loader → Splitter → Embedding → Vector Store) ──────
  const handleIngest = useCallback(async () => {
    if (!docLoaderNode || !vectorStoreNode) return
    setIngestStatus('running')
    setIngestMsg('')

    const loaderData = docLoaderNode.data
    const splitterData = splitterNode?.data
    const embData = embeddingNode?.data
    const vsData = vectorStoreNode.data

    const collection = vsData.collection_name || 'default'
    const splitterType = splitterData?.splitter_type ?? 'recursive_character'
    const chunkSize = splitterData?.chunk_size ?? 512
    const chunkOverlap = splitterData?.chunk_overlap ?? 50
    const embProvider = embData?.provider ?? 'local'
    const embModel = embData?.model ?? 'sentence-transformers/all-MiniLM-L6-v2'
    // resolve through global credentials store
    const embApiKey = resolveApiKey(embProvider, embData?.api_key)
    const source = loaderData.source ?? ''

    // Resolve linked connection node (if any)
    const linkedConnNode = (() => {
      const linkedIds = edges
        .filter((e) => e.source === docLoaderNode.id || e.target === docLoaderNode.id)
        .map((e) => (e.source === docLoaderNode.id ? e.target : e.source))
      return nodes.find(
        (n) => n.type === 'connection' && linkedIds.includes(n.id),
      ) as Node<ConnectionNodeData, 'connection'> | undefined
    })()

    if (DB_LOADER_TYPES.has(loaderData.loader_type)) {
      try {
        // Clear stale chunks first so embedding model changes take effect
        await fetch(`${API_BASE}/api/retrieval/collections/${encodeURIComponent(collection)}`, { method: 'DELETE' })

        const connConfig = linkedConnNode?.data?.config || {}
        const payload = {
          db_type: loaderData.loader_type,
          connection_string: source || connConfig.connection_string || undefined,
          host: connConfig.host || undefined,
          port: connConfig.port ? Number(connConfig.port) : (loaderData.loader_type === 'postgres' ? 5433 : undefined),
          database: connConfig.database || undefined,
          user: connConfig.user || undefined,
          password: connConfig.password || undefined,
          table: loaderData.db_table || undefined,
          query: loaderData.db_query || undefined,
          collection,
          splitter_type: splitterType,
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          embedding_provider: embProvider,
          embedding_model: embModel,
          embedding_api_key: embApiKey,
          store_type: vsData.store_type,
          vector_store_dsn: vsData.connection_string || '',
        }

        const res = await fetch(`${API_BASE}/api/retrieval/ingest/database`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })

        if (!res.ok) {
          const err = await res.text().catch(() => res.statusText)
          setIngestStatus('error')
          setIngestMsg(`Database ingest failed: ${err}`)
          return
        }

        const data = await res.json()
        if (!data.success) {
          setIngestStatus('error')
          setIngestMsg(`Database ingest failed: ${data.error || data.detail || 'Unknown error'}`)
          return
        }

        setIngestStatus('done')
        const tablesStr = data.tables?.length ? ` from tables [${data.tables.join(', ')}]` : ''
        setIngestMsg(`✓ Ingested ${data.records_ingested ?? 0} records (${data.chunks_ingested ?? 0} chunks)${tablesStr} into "${collection}"`)
      } catch (e: any) {
        setIngestStatus('error')
        setIngestMsg(`Database ingest error: ${e.message}`)
      }
      return
    }

    try {
      if (source) {
        // Clear stale chunks first so embedding model changes take effect
        await fetch(`${API_BASE}/api/retrieval/collections/${encodeURIComponent(collection)}`, { method: 'DELETE' })

        // The backend runs this node's loader (file, folder, URL, feed, …), then splits and embeds
        const res = await fetch(`${API_BASE}/api/retrieval/ingest/loader`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            loader_type: loaderData.loader_type,
            source,
            loader_config: {
              db_table: loaderData.db_table, db_query: loaderData.db_query,
              ocr_engine: loaderData.ocr_engine, ocr_language: loaderData.ocr_language,
              ocr_provider: loaderData.ocr_provider, ocr_model: loaderData.ocr_model,
            },
            connection: linkedConnNode?.data?.config ?? {},
            collection,
            splitter_type: splitterType,
            chunk_size: chunkSize,
            chunk_overlap: chunkOverlap,
            embedding_provider: embProvider,
            embedding_model: embModel,
            embedding_api_key: embApiKey,
            store_type: vsData.store_type,
            vector_store_dsn: vsData.connection_string || '',
          }),
        })
        if (!res.ok) {
          const body = await res.json().catch(() => null)
          setIngestStatus('error')
          setIngestMsg(`Ingest failed: ${body?.detail ?? res.statusText}`)
          return
        }
        const data = await res.json()
        setIngestStatus('done')
        setIngestMsg(`✓ Loaded ${data.documents_loaded} document${data.documents_loaded === 1 ? '' : 's'} → ${data.chunks_ingested} chunks in "${collection}"`)
      } else {
        setIngestStatus('error')
        setIngestMsg('Set the source on the Doc Loader node (file path, folder, URL…).')
      }
    } catch (e: any) {
      setIngestStatus('error')
      setIngestMsg(`Ingest error: ${e.message}`)
    }
  }, [docLoaderNode, vectorStoreNode, splitterNode, embeddingNode, nodes, edges, resolveApiKey])

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !isRunning) {
        e.preventDefault()
        onRun()
      }
    },
    [onRun, isRunning],
  )

  const toggleStep = (key: string) =>
    setExpandedSteps((prev) => ({ ...prev, [key]: !prev[key] }))

  const lastAssistant = [...history].reverse().find((t) => t.role === 'assistant' || t.role === 'agent_run')

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="runner-panel-body">
      <div className="runner-header-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {hasMemory && (
            <button
              type="button"
              className="runner-clear-btn"
              onClick={handleNewSession}
              disabled={isRunning}
              style={{
                background: '#eff6ff',
                color: '#2563eb',
                border: '1px solid #bfdbfe',
                fontWeight: 600,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
              title="Start a brand new chat thread with a fresh Session ID"
            >
              <span>+</span> New Chat Session
            </button>
          )}
          {history.length > 0 && (
            <button type="button" className="runner-clear-btn" onClick={handleClear} disabled={isRunning}>
              Clear
            </button>
          )}
        </div>
        {canIngest && (
          <button
            type="button"
            className="runner-clear-btn"
            onClick={handleIngest}
            disabled={ingestStatus === 'running'}
            style={{
              marginLeft: 'auto',
              background: ingestStatus === 'done' ? '#dcfce7' : ingestStatus === 'error' ? '#fee2e2' : '#eff6ff',
              color: ingestStatus === 'done' ? '#15803d' : ingestStatus === 'error' ? '#b91c1c' : '#1d4ed8',
              border: `1px solid ${ingestStatus === 'done' ? '#86efac' : ingestStatus === 'error' ? '#fca5a5' : '#bfdbfe'}`,
              fontWeight: 600,
              fontSize: 11,
              padding: '3px 10px',
              borderRadius: 5,
              cursor: ingestStatus === 'running' ? 'wait' : 'pointer',
            }}
            title="Ingest the document into the vector store so the retriever can find it"
          >
            {ingestStatus === 'running' ? '⏳ Ingesting…' : ingestStatus === 'done' ? '✓ Ingested' : ingestStatus === 'error' ? '✗ Failed' : '📥 Ingest Document'}
          </button>
        )}
      </div>
      {ingestMsg && (
        <div style={{
          fontSize: 11, padding: '4px 8px', borderRadius: 4, marginBottom: 4,
          background: ingestStatus === 'done' ? '#f0fdf4' : '#fef2f2',
          color: ingestStatus === 'done' ? '#15803d' : '#b91c1c',
          border: `1px solid ${ingestStatus === 'done' ? '#bbf7d0' : '#fecaca'}`,
        }}>
          {ingestMsg}
        </div>
      )}

      {/* Status banner */}
      {isAgentMode ? (
        <div className="runner-meta-banner runner-agent-banner">
          <span>🤖 <strong>Agent Mode</strong></span>
          <span>Strategy: <strong>{masterAgentNode!.data.strategy}</strong></span>
          <span>Children: <strong>{childCount}</strong></span>
          <span>Max steps: <strong>{masterAgentNode!.data.max_steps}</strong></span>
        </div>
      ) : isWorkflowMode ? (
        <div className="runner-meta-banner">
          <span>🔀 <strong>Workflow Mode</strong></span>
          <span>Steps: <strong>{nodes.filter((n) => n.type === 'wf_step').length}</strong></span>
          <span>Tools: <strong>{toolCount}</strong></span>
        </div>
      ) : (
        <div className="runner-meta-banner runner-meta-banner--compact" title="What this run will use">
          <strong title={modelTitle || undefined}>
            {modelNames.length ? modelNames[0] : 'No model'}
            {modelNames.length > 1 ? ` +${modelNames.length - 1}` : ''}
          </strong>
          <span title={toolTitle || undefined}>{totalToolCount} tool{totalToolCount === 1 ? '' : 's'}</span>
          <span>memory {anyMemory ? 'on' : 'off'}</span>
          <span>cache {anyCache ? 'on' : 'off'}</span>
        </div>
      )}

      {subSummary && (subSummary.pipelines.length > 0 || subSummary.errors.length > 0) && (
        <div className="runner-subpipelines" title="Published pipelines this run calls, at their pinned versions">
          {subSummary.pipelines.map((p) => {
            const src = `${p.name} v${p.version}`
            const m = subModels.filter((x) => x.sources.includes(src))
            const t = subTools.filter((x) => x.source === src).length
            return (
              <div key={`${p.app_id}-${p.version}-${p.called_from}`} className="runner-subpipeline-row" style={{ paddingLeft: p.depth * 12 }}>
                <span className="runner-subpipeline-name">{p.depth > 0 ? '↳ ' : ''}{src}</span>
                <span title={m.map((x) => `${x.model} (${x.provider})`).join('\n') || undefined}>
                  {m.length ? m.map((x) => x.model).join(', ') : 'no model'}
                </span>
                <span>{t} tool{t === 1 ? '' : 's'}</span>
              </div>
            )
          })}
          {subSummary.errors.map((e) => (
            <div key={e} className="runner-subpipeline-error">⚠ {e}</div>
          ))}
        </div>
      )}

      {blockingIssues.length > 0 && (
        <div className="runner-validation-box">
          <div className="runner-validation-title">Fix these blocking issues before running:</div>
          <div className="runner-validation-list">
            {blockingIssues.slice(0, 4).map((issue) => {
              const isConnectionIssue = issue.id.startsWith('connection-error-')
              return (
                <div key={issue.id} className="runner-validation-item">
                  <div className="runner-validation-text">
                    <span>• {issue.title}</span>
                    {isConnectionIssue && <span className="runner-validation-hint">{issue.hint}</span>}
                  </div>
                  <div className="runner-validation-actions">
                    {isConnectionIssue && onUpdateNodeData && (
                      <button
                        type="button"
                        className="runner-validation-fix-btn"
                        onClick={() => handleRetestConnection(issue.nodeId!)}
                        disabled={retestingNodeId === issue.nodeId}
                      >
                        {retestingNodeId === issue.nodeId ? 'Testing…' : 'Retest'}
                      </button>
                    )}
                    {issue.nodeId && onFocusNode && (
                      <button
                        type="button"
                        className="runner-validation-fix-btn"
                        onClick={() => onFocusNode(issue.nodeId!)}
                      >
                        Fix
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="runner-tab-bar">
        <button
          type="button"
          className={`runner-tab${activeTab === 'chat' ? ' active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >Chat</button>
        <button
          type="button"
          className={`runner-tab${activeTab === 'raw' ? ' active' : ''}`}
          onClick={() => setActiveTab('raw')}
        >Raw output</button>
        <button
          type="button"
          className={`runner-tab${activeTab === 'logs' ? ' active' : ''}`}
          onClick={() => setActiveTab('logs')}
        >Logs{appLogs.length > 0 ? ` (${appLogs.length})` : ''}</button>
      </div>

      {/* ── Chat view ── */}
      {activeTab === 'chat' && (
        <div className="chat-history">
          {history.length === 0 && (
            <div className="chat-empty">
              {!canRun ? (
                <p className="chat-empty-title">Add an LLM, Master Agent or Pipeline node to the canvas to start running prompts.</p>
              ) : isBlocked ? (
                <>
                  <p className="chat-empty-title">Can't run “{appName || 'this pipeline'}” yet</p>
                  <p className="chat-empty-sub">Fix the blocking issue{blockingIssues.length === 1 ? '' : 's'} above, then try again.</p>
                </>
              ) : (
                <>
                  <p className="chat-empty-title">
                    {isAgentMode
                      ? `Ready — master + ${childCount} child agent${childCount === 1 ? '' : 's'}`
                      : `Ready to run${appName ? ` “${appName}”` : ''}`}
                  </p>
                  <div className="chat-empty-sub-row">
                    <p className="chat-empty-sub">{isAgentMode ? 'Describe a goal, or start from an example:' : 'Type a prompt below, or start from an example:'}</p>
                    <button
                      type="button"
                      className="suggested-prompts-refresh"
                      onClick={generatePrompts}
                      disabled={generatingPrompts || isRunning}
                      title="Read this pipeline and generate example prompts with its model"
                    >
                      {generatingPrompts ? 'Generating…' : aiPrompts ? '↻ Regenerate' : '✨ Generate from pipeline'}
                    </button>
                  </div>
                  {promptGenError && <p className="suggested-prompts-error">{promptGenError}</p>}
                  <div className="suggested-prompts-row">
                    {displayedPrompts.map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        className="suggested-prompt-card"
                        onClick={() => applySuggestedPrompt(suggestion)}
                        disabled={isRunning}
                      >
                        <span className="suggested-prompt-text">{suggestion}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {history.map((turn, idx) => {
            if (turn.role === 'user') {
              return (
                <div key={idx} className="chat-turn chat-turn--user">
                  <div className="chat-turn-label">👤 You</div>
                  <div className="chat-bubble">{turn.content}</div>
                </div>
              )
            }

            // ── Agent run turn ──────────────────────────────────────────────
            if (turn.role === 'agent_run') {
              const maxStepDuration = Math.max(1, ...((turn.agentSteps ?? []).map((s) => s.duration_ms || 0)))
              return (
                <div key={idx} className="chat-turn chat-turn--agent-run">
                  <div className="chat-turn-label">
                    🤖 Master Agent
                    {turn.agentStrategy && (
                      <span className="chat-agent-strategy-badge">{turn.agentStrategy}</span>
                    )}
                    {!turn.isStreaming && turn.steps > 0 && (
                      <span className="chat-steps-badge">{turn.steps} steps</span>
                    )}
                    {!turn.isStreaming && (turn.agentRetrySteps ?? 0) > 0 && (
                      <span className="chat-steps-badge" style={{ background: '#fff7ed', color: '#9a3412', border: '1px solid #fed7aa' }}>
                        ↻ retry steps {turn.agentRetrySteps}
                      </span>
                    )}
                    {!turn.isStreaming && (turn.agentFallbackSteps ?? 0) > 0 && (
                      <span className="chat-steps-badge" style={{ background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' }}>
                        ⇄ fallback steps {turn.agentFallbackSteps}
                      </span>
                    )}
                  </div>

                  {/* Step trace */}
                  {turn.isStreaming && (!turn.agentSteps || turn.agentSteps.length === 0) && (
                    <div className="agent-run-thinking">
                      <span className="chat-thinking">🔄 Orchestrating agents…</span>
                    </div>
                  )}

                  {(turn.agentSteps ?? []).length > 0 && (
                    <div className="agent-steps-trace">
                      {(turn.agentSteps ?? []).map((step, si) => {
                        const key = `${idx}-${si}`
                        const isOpen = expandedSteps[key] ?? false
                        const ismaster = step.agent === 'Master Agent'
                        return (
                          <div
                            key={si}
                            className={`agent-step-row ${ismaster ? 'agent-step-master' : 'agent-step-child'}`}
                          >
                            <button
                              type="button"
                              className="agent-step-header"
                              onClick={() => toggleStep(key)}
                            >
                              <span className="agent-step-icon">{ismaster ? '🤖' : '🧑‍💻'}</span>
                              <span className="agent-step-name">{step.agent}</span>
                              <span className="agent-step-role-badge">{step.role}</span>
                              {(step.attempt_count ?? 1) > 1 && (
                                <span className="agent-step-role-badge" style={{ background: '#fff7ed', color: '#9a3412', border: '1px solid #fed7aa' }}>
                                  ↻ {step.attempt_count}
                                </span>
                              )}
                              {step.used_fallback && (
                                <span className="agent-step-role-badge" style={{ background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' }}>
                                  ⇄ fallback
                                </span>
                              )}
                              <span className="agent-step-ms">{step.duration_ms}ms</span>
                              <span className="agent-step-chevron">{isOpen ? '▲' : '▼'}</span>
                            </button>
                            <div style={{ padding: '0 10px 8px' }}>
                              <div style={{ height: 6, background: '#eef2ff', borderRadius: 999, overflow: 'hidden' }}>
                                <div
                                  style={{
                                    width: `${Math.max(4, Math.round((step.duration_ms / maxStepDuration) * 100))}%`,
                                    height: '100%',
                                    background: step.used_fallback ? '#60a5fa' : '#6366f1',
                                  }}
                                />
                              </div>
                              {(step.effective_provider && step.effective_model) && (
                                <div style={{ marginTop: 4, fontSize: 10, color: '#64748b' }}>
                                  Active model: {step.effective_provider}/{step.effective_model}
                                </div>
                              )}
                            </div>
                            {isOpen && (
                              <div className="agent-step-body">
                                <div className="agent-step-section">
                                  <span className="agent-step-label">Input</span>
                                  <pre className="agent-step-code">{step.input}</pre>
                                </div>
                                <div className="agent-step-section">
                                  <span className="agent-step-label">
                                    Output
                                    {!ismaster && onUpdateNodeData && (() => {
                                      const child = nodes.find((n) => n.type === 'child_agent' && (n.data as ChildAgentNodeData).label === step.agent)
                                      return child ? (
                                        <button type="button" className="debug-pin-btn" title="Pin this output to the agent: later runs use it instead of running it"
                                          onClick={() => pinOutput(child.id, step.output)}>📌 Pin</button>
                                      ) : null
                                    })()}
                                  </span>
                                  <pre className="agent-step-code">{step.output}</pre>
                                </div>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {/* Paused at a human gate: review the output, then approve / edit / reject */}
                  {turn.pendingGate && !turn.isStreaming && (() => {
                    const gate = turn.pendingGate
                    const draft = gateDrafts[turn.agentRunId ?? ''] ?? { edited: gate.output, comment: '' }
                    const setDraft = (d: Partial<typeof draft>) =>
                      setGateDrafts((prev) => ({ ...prev, [turn.agentRunId ?? '']: { ...draft, ...d } }))
                    const isEdit = gate.gate_type === 'edit'
                    const edited = isEdit && draft.edited !== gate.output
                    const decide = (action: GateDecision['action']) => {
                      const decision: GateDecision = { action, comment: draft.comment.trim() || undefined }
                      if (action === 'edit') decision.edited_output = draft.edited
                      setGateDrafts((prev) => { const next = { ...prev }; delete next[turn.agentRunId ?? '']; return next })
                      resumeAgentRun(turn, decision)
                    }
                    return (
                      <div className="agent-gate-card" role="region" aria-label="Human review">
                        <div className="agent-gate-title">
                          ✋ {gate.label} — <strong>{gate.agent}</strong>
                          <span className="agent-gate-type">{gate.gate_type}</span>
                        </div>
                        <div className="agent-gate-message">{gate.prompt_message}</div>
                        {isEdit ? (
                          <textarea
                            className="agent-gate-output agent-gate-output--edit"
                            value={draft.edited}
                            onChange={(e) => setDraft({ edited: e.target.value })}
                            rows={Math.min(14, Math.max(4, draft.edited.split('\n').length + 1))}
                            aria-label="Output to approve (editable)"
                          />
                        ) : (
                          <pre className="agent-gate-output">{gate.output}</pre>
                        )}
                        <input
                          className="agent-gate-comment"
                          placeholder="Comment (optional — saved with the decision)"
                          value={draft.comment}
                          onChange={(e) => setDraft({ comment: e.target.value })}
                        />
                        <div className="agent-gate-actions">
                          <button type="button" className="agent-gate-btn agent-gate-btn--approve" disabled={isRunning}
                            onClick={() => decide(edited ? 'edit' : 'approve')}>
                            {edited ? '✓ Approve with edits' : gate.gate_type === 'review' ? '✓ Mark reviewed' : '✓ Approve'}
                          </button>
                          <button type="button" className="agent-gate-btn agent-gate-btn--reject" disabled={isRunning}
                            onClick={() => decide('reject')}>✕ Reject</button>
                          {gate.expires_at && (
                            <span className="agent-gate-expiry">
                              Times out {new Date(gate.expires_at + 'Z').toLocaleString()} → {gate.on_timeout}
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })()}

                  {/* Interrupted or failed: finished steps are checkpointed, so it can pick up where it stopped */}
                  {!turn.isStreaming && (turn.agentStatus === 'interrupted' || turn.agentStatus === 'failed') && turn.agentRunId && (
                    <div className="agent-resume-bar">
                      <span>
                        {turn.agentStatus === 'interrupted' ? '⏸ Run interrupted.' : '⚠ Run failed.'}{' '}
                        Finished steps are saved on the server, so resuming continues after the last one.
                      </span>
                      <button type="button" className="agent-gate-btn agent-gate-btn--approve" disabled={isRunning}
                        onClick={() => resumeAgentRun(turn)}>↻ Resume</button>
                    </div>
                  )}

                  {/* Final answer */}
                  {turn.content && (turn.agentStatus === 'completed' || turn.agentStatus === undefined) && (
                    <div className="agent-final-answer">
                      <span className="agent-final-label">
                        ✅ Final Answer
                        {(turn.agentResumedSteps ?? 0) > 0 && (
                          <span className="agent-resumed-badge">resumed · {turn.agentResumedSteps} step(s) reused</span>
                        )}
                      </span>
                      <div className="chat-bubble agent-final-bubble">{turn.content}</div>
                      {!turn.isStreaming && turn.agentRunId && turn.agentStatus === 'completed' && (
                        <div className="chat-meta-footer"><RunRating runId={turn.agentRunId} /></div>
                      )}
                    </div>
                  )}
                  {turn.content && (turn.agentStatus === 'failed' || turn.agentStatus === 'rejected' || turn.agentStatus === 'interrupted') && (
                    <div className="chat-bubble agent-error-bubble">{turn.content}</div>
                  )}
                  {turn.isStreaming && !turn.content && (
                    <div className="chat-bubble"><span className="chat-thinking">thinking…</span></div>
                  )}
                  <TurnLogs logs={allLogs} runId={turn.runId} />
                </div>
              )
            }

            // ── Normal LLM turn ─────────────────────────────────────────────
            return (
              <div key={idx} className={`chat-turn chat-turn--${turn.role}`}>
                <div className="chat-turn-label">
                  {isWorkflowMode ? '🔀 Workflow' : `🤖 ${primaryLlmNode?.data.model ?? 'Agent'}`}
                  {turn.steps > 1 && (
                    <span className="chat-steps-badge">{turn.steps} steps</span>
                  )}
                </div>

                {turn.ragSources && turn.ragSources.length > 0 && (
                  <div className="chat-rag-sources">
                    <details className="chat-rag-sources-details" open={false}>
                      <summary className="chat-rag-sources-summary">
                        <span className="chat-rag-icon">📚</span>
                        <span className="chat-rag-title">
                          Retrieved Sources ({turn.ragSources.length} chunk{turn.ragSources.length > 1 ? 's' : ''})
                        </span>
                        <span className="chat-rag-badge">RAG Context</span>
                      </summary>
                      <div className="chat-rag-list">
                        {turn.ragSources.map((src, sIdx) => {
                          const fileName = src.source.split('/').pop() || src.source
                          return (
                            <div key={sIdx} className="chat-rag-item">
                              <div className="chat-rag-item-header">
                                <span className="chat-rag-doc-name" title={src.source}>
                                  📄 {fileName}
                                </span>
                                {src.score !== undefined && src.score > 0 && (
                                  <span className="chat-rag-score-chip">
                                    Sim: {(src.score * 100).toFixed(1)}%
                                  </span>
                                )}
                              </div>
                              <div className="chat-rag-snippet">
                                {src.content.length > 250 ? `${src.content.slice(0, 250)}…` : src.content}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </details>
                  </div>
                )}

                {turn.toolCalls.length > 0 && (
                  <div className="chat-tool-calls">
                    {turn.toolCalls.map((tc, ti) => (
                      <details key={ti} className="chat-tool-call" open={tc.output === undefined}>
                        <summary className="chat-tool-call-summary">
                          <span className="chat-tool-icon">🔧</span>
                          <span className="chat-tool-name">
                            {tc.name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                          </span>
                          {tc.output === undefined
                            ? <span className="chat-tool-running">running…</span>
                            : <span className="chat-tool-done">✓ done</span>
                          }
                        </summary>
                        <div className="chat-tool-detail">
                          <div className="chat-tool-input">
                            <span className="chat-tool-detail-label">Input</span>
                            <pre className="chat-tool-code">{tc.input}</pre>
                          </div>
                          {tc.output !== undefined && (
                            <div className="chat-tool-output">
                              <span className="chat-tool-detail-label">
                                Output
                                {tc.nodeId && onUpdateNodeData && (
                                  <button type="button" className="debug-pin-btn" title="Pin this output to the tool node: later runs use it instead of calling the tool"
                                    onClick={() => pinOutput(tc.nodeId!, tc.output ?? '', turn.llmRunId, tc.stepKey)}>📌 Pin</button>
                                )}
                              </span>
                              <pre className="chat-tool-code">{tc.output}</pre>
                            </div>
                          )}
                        </div>
                      </details>
                    ))}
                  </div>
                )}

                <div className="chat-bubble">
                  {turn.content
                    ? renderContent(turn.content, turn.outputFormat ?? 'auto')
                    : turn.isStreaming
                      ? <span className="chat-thinking">thinking…</span>
                      : null
                  }
                  {turn.isStreaming && turn.content && <span className="stream-cursor" />}
                </div>

                {/* Paused at a breakpoint: see and edit the step's input, then continue or step */}
                {!turn.isStreaming && turn.llmStatus === 'paused' && turn.debugPause && (
                  <DebugPauseCard key={turn.debugPause.step} pause={turn.debugPause} disabled={isRunning}
                    onContinue={(override, step) => continueDebug(turn, override, step)}
                    onStop={() => stopDebug(turn)} />
                )}

                {/* Failed or cut off: finished model and tool calls are checkpointed, so it can pick up where it stopped */}
                {!turn.isStreaming && (turn.llmStatus === 'interrupted' || turn.llmStatus === 'failed') && turn.llmRunId && (
                  <div className="agent-resume-bar">
                    <span>
                      {turn.llmStatus === 'interrupted' ? '⏸ Run interrupted.' : '⚠ Run failed.'}{' '}
                      Finished model and tool calls are saved on the server, so resuming continues after the last one.
                    </span>
                    <button type="button" className="agent-gate-btn agent-gate-btn--approve" disabled={isRunning}
                      onClick={() => resumeLlmRun(turn)}>↻ Resume</button>
                  </div>
                )}

                {turn.meta && !turn.isStreaming && (
                  <div className="chat-meta-footer">
                    <span title={`${turn.meta.provider}/${turn.meta.model}`}>{turn.meta.model}</span>
                    {turn.meta.latency_ms != null && (
                      <span>· {(turn.meta.latency_ms / 1000).toFixed(1)}s</span>
                    )}
                    {turn.meta.usage && (() => {
                      const u = turn.meta.usage
                      const total = u.total_tokens ?? (u.prompt_tokens ?? 0) + (u.completion_tokens ?? 0)
                      return total ? (
                        <span title={`prompt ${u.prompt_tokens ?? '–'} · completion ${u.completion_tokens ?? '–'}`}>
                          · {total.toLocaleString()} tokens
                        </span>
                      ) : null
                    })()}
                    {turn.ragSources && turn.ragSources.length > 0 && (
                      <span className="meta-badge rag" style={{ background: '#ecfdf5', color: '#065f46', border: '1px solid #a7f3d0' }}>
                        📚 {turn.ragSources.length} source{turn.ragSources.length > 1 ? 's' : ''}
                      </span>
                    )}
                    {turn.outputFormat && turn.outputFormat !== 'auto' && (() => {
                      const opt = FORMAT_OPTIONS.find(f => f.value === turn.outputFormat)
                      return (
                        <span className="meta-badge" style={{ background: '#ede9fe', color: '#5b21b6', border: '1px solid #c4b5fd' }}>
                          {opt?.icon} {opt?.label ?? turn.outputFormat}
                        </span>
                      )
                    })()}
                    {(turn.llmResumedSteps ?? 0) > 0 && (
                      <span className="agent-resumed-badge">resumed · {turn.llmResumedSteps} step(s) reused</span>
                    )}
                    {(turn.skillsLoaded ?? []).map((sk) => (
                      <span key={sk.name} className="meta-badge" title={sk.tools.length ? `Tools switched on: ${sk.tools.join(', ')}` : 'Loaded skill'}
                        style={{ background: '#fefce8', color: '#854d0e', border: '1px solid #fde68a' }}>
                        🧩 {sk.name}{sk.version ? ` v${sk.version}` : ''}
                      </span>
                    ))}
                    {turn.meta.cache_hit && <span className="meta-badge cache">⚡ cache</span>}
                    {turn.meta.simulated && <span className="meta-badge sim">sim</span>}
                    {turn.meta.attempt_count && turn.meta.attempt_count > 1 && (
                      <span className="meta-badge" style={{ background: '#fff7ed', color: '#9a3412', border: '1px solid #fed7aa' }}>
                        ↻ attempts {turn.meta.attempt_count}
                      </span>
                    )}
                    {turn.meta.used_fallback && (
                      <span className="meta-badge" style={{ background: '#eff6ff', color: '#1d4ed8', border: '1px solid #bfdbfe' }}>
                        ⇄ fallback
                      </span>
                    )}
                    {turn.meta.effective_provider && turn.meta.effective_model &&
                      (`${turn.meta.effective_provider}/${turn.meta.effective_model}` !== `${turn.meta.provider}/${turn.meta.model}`) && (
                        <span className="meta-badge" style={{ background: '#f0f9ff', color: '#0c4a6e', border: '1px solid #bae6fd' }}>
                          active {turn.meta.effective_provider}/{turn.meta.effective_model}
                        </span>
                    )}
                    {(turn.llmRunId ?? turn.meta.run_id) && turn.llmStatus !== 'failed' && turn.llmStatus !== 'interrupted' && (
                      <RunRating runId={(turn.llmRunId ?? turn.meta.run_id)!} />
                    )}
                    {primaryLlmNode && onUpdateNodeData && turn.content && turn.llmStatus === 'completed' && (
                      <button type="button" className="debug-pin-btn" title="Pin this answer to the LLM node: later runs use it instead of calling the model, so the nodes after it can be tested for free"
                        onClick={() => pinOutput(primaryLlmNode.id, turn.rawContent ?? turn.content)}>📌 Pin answer</button>
                    )}
                    {turn.content && (
                      <button
                        type="button"
                        className="chat-copy-btn"
                        onClick={() => { navigator.clipboard.writeText(turn.rawContent ?? turn.content); setCopiedIdx(idx); setTimeout(() => setCopiedIdx(null), 1500) }}
                      >
                        {copiedIdx === idx ? '✓ Copied' : 'Copy'}
                      </button>
                    )}
                  </div>
                )}

                <TurnLogs logs={allLogs} runId={turn.runId} />
              </div>
            )
          })}
          <div ref={bottomRef} />
        </div>
      )}

      {/* ── Raw output view ── */}
      {activeTab === 'raw' && (
        <div className="raw-output-pane">
          <div className="raw-output-toolbar">
            {lastAssistant?.content && (
              <button
                type="button"
                className="copy-btn"
                onClick={() => navigator.clipboard.writeText(lastAssistant!.content)}
              >Copy</button>
            )}
          </div>
          <pre className={`response-box${isRunning ? ' streaming' : ''}`}>
            {lastAssistant?.content
              ? <>{lastAssistant.rawContent ?? lastAssistant.content}{isRunning && <span className="stream-cursor" />}</>
              : <span className="response-placeholder">No output yet.</span>
            }
          </pre>
        </div>
      )}

      {/* ── Logs view (this pipeline; all pipelines live under Operations → Logs) ── */}
      {activeTab === 'logs' && (
        <div className="raw-output-pane">
          <div className="raw-output-toolbar">
            <button
              type="button"
              className="copy-btn"
              disabled={appLogs.length === 0}
              onClick={() => navigator.clipboard.writeText(logsToText(appLogs))}
            >Copy</button>
            <button
              type="button"
              className="copy-btn"
              disabled={appLogs.length === 0 || isRunning}
              onClick={() => clearRunLogs(appId ?? '')}
            >Clear logs</button>
          </div>
          <RunLogList
            logs={appLogs}
            autoScroll
            emptyText="No logs yet. Run a prompt to see pipeline activity."
          />
        </div>
      )}

      {/* Error */}
      {error && <div className="runner-error">{error}</div>}

      {/* Prompt input + send */}
      <div className="runner-input-area">

        <textarea
          ref={promptRef}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          placeholder={isBlocked
            ? 'Fix the blocking issues above to run…'
            : isAgentMode
              ? 'Describe a goal for the Master Agent…'
              : isWorkflowMode
                ? 'Type a message or answer the workflow…'
                : 'Type a prompt…'}
          className="field-textarea runner-textarea"
          disabled={isRunning || isBlocked}
        />
        <div className="runner-btn-row">
          <label className="runner-format">
            <span>Format</span>
            <select value={outputFormat} onChange={(e) => setOutputFormat(e.target.value as OutputFormat)} disabled={isRunning}>
              {FORMAT_OPTIONS.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
            </select>
          </label>
          {isRunning && (
            <span className="stream-indicator">
              <span className="stream-dot" />
              {isAgentMode ? 'Running agents…' : 'Streaming…'}
            </span>
          )}
          <button
            type="button"
            className={`run-prompt-btn${isRunning ? ' running' : ''}`}
            onClick={isRunning ? handleStop : onRun}
            disabled={(!canRun || blockingIssues.length > 0) && !isRunning}
          >
            {isRunning ? 'Stop' : isAgentMode ? 'Run agents' : isWorkflowMode ? 'Send' : 'Run'}
            {!isRunning && <kbd className="run-prompt-kbd">⌘↵</kbd>}
          </button>
        </div>
      </div>
    </div>
  )
}
