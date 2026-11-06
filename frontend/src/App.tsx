import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent as ReactMouseEvent } from 'react'
import { CredentialsProvider } from './context/CredentialsContext'
import { useCredentials } from './context/CredentialsContext'
import { useExecution } from './context/ExecutionContext'
import { useTenantContext } from './context/TenantContext'
import { useAuth } from './context/AuthContext'
import { MarketplaceView } from './components/marketplace/MarketplaceView'
import { PublishListingModal } from './components/marketplace/PublishListingModal'
import { ChatLinksModal } from './components/ChatLinksPanel'
import { AppSwitcher } from './components/AppSwitcher'
import { FitViewOnOpen } from './components/FitViewOnOpen'
import { recordRecentNode } from './utils/recentNodes'
import {
  Background,
  BackgroundVariant,
  ControlButton,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import './App.css'
import './styles/top-nav.css'

import { API_BASE } from './types'
import { instantiateSavedAgent, instantiateSpec } from './utils/savedAgents'
import type { SavedAgent } from './utils/savedAgents'
import type {
  FlowNode,
  ToolCatalogItem,
  ToolkitNodeData,
  ToolkitSubTool,
  AppRecord,
  MemoryNodeData,
  CacheNodeData,
  DocLoaderNodeData,
  TextSplitterNodeData,
  EmbeddingNodeData,
  VectorStoreNodeData,
  KnowledgeBaseRecord,
  ConnectionRecord,
  ConnectionNodeData,
  SkillRecord,
  SyntheticDataNodeData,
  DebugNodeFields,
} from './types'
import { nodeTypes } from './nodes'
import { edgeTypes } from './nodes/DeletableEdge'
import { Redo2, Undo2 } from 'lucide-react'
import { useFlowManager } from './hooks/useFlowManager'
import { useAppManager } from './hooks/useAppManager'
import { useSidebarState } from './hooks/useSidebarState'
import { useCatalogData } from './hooks/useCatalogData'
import { Sidebar } from './components/Sidebar'
import { RightPanel } from './components/RightPanel'
import { TopNav } from './components/TopNav'
import { MonitorView } from './components/MonitorView'
import { AutomationView } from './components/AutomationView'
import { SettingsView } from './components/settings/SettingsView'
import { EvalPanel } from './components/EvalPanel'
import { AppsHubView } from './components/AppsHubView'
import { LabView } from './components/LabView'
import { OPEN_DOCS_EVENT, type OpenDocsDetail } from './utils/docLinks'

// The user guide is loaded only when Docs is opened (it bundles every guide)
const DocsView = lazy(() => import('./components/docs/DocsView').then((m) => ({ default: m.DocsView })))
import './styles/lab.css'
import './styles/schedules.css'
import type { TopView, MonitorTab, AutomationTab, SettingsTab } from './components/TopNav'
import { buildAppUrl, parseAppUrl, type RightPanelTab } from './utils/appUrl'
import { ExportModal } from './components/ExportModal'
import { PipelinePreviewModal } from './components/PipelinePreviewModal'
import { CustomToolModal } from './components/CustomToolModal'
import type { CustomToolRecord } from './components/CustomToolModal'
import { CustomMcpModal } from './components/CustomMcpModal'
import { ConnectionModal } from './components/ConnectionModal'
import { NodeDebugSection, DEBUGGABLE_NODE_TYPES } from './components/config/NodeDebugSection'
import { LlmConfigPanel } from './components/config/LlmConfigPanel'
import { ToolConfigPanel } from './components/config/ToolConfigPanel'
import { ToolkitConfigPanel } from './components/config/ToolkitConfigPanel'
import { MemoryConfigPanel } from './components/config/MemoryConfigPanel'
import { CacheConfigPanel } from './components/config/CacheConfigPanel'
import { DocLoaderConfigPanel } from './components/config/DocLoaderConfigPanel'
import { TextSplitterConfigPanel } from './components/config/TextSplitterConfigPanel'
import { EmbeddingConfigPanel } from './components/config/EmbeddingConfigPanel'
import { VectorStoreConfigPanel } from './components/config/VectorStoreConfigPanel'
import { RetrieverConfigPanel } from './components/config/RetrieverConfigPanel'
import { MasterAgentConfigPanel } from './components/config/MasterAgentConfigPanel'
import { ChildAgentConfigPanel } from './components/config/ChildAgentConfigPanel'
import { ConnectionConfigPanel } from './components/config/ConnectionConfigPanel'
import { KnowledgeBaseConfigPanel } from './components/config/KnowledgeBaseConfigPanel'
import { GatewayConfigPanel } from './components/config/GatewayConfigPanel'
import { SkillConfigPanel } from './components/config/SkillConfigPanel'
import { RerankerConfigPanel } from './components/config/RerankerConfigPanel'
import { HumanGateConfigPanel } from './components/config/HumanGateConfigPanel'
import { CheckpointerConfigPanel } from './components/config/CheckpointerConfigPanel'
import { WorkflowStepConfigPanel } from './components/config/WorkflowStepConfigPanel'
import { OutputParserConfigPanel } from './components/config/OutputParserConfigPanel'
import { MiddlewareConfigPanel } from './components/config/MiddlewareConfigPanel'
import { SyntheticDataConfigPanel } from './components/config/SyntheticDataConfigPanel'
import { KnowledgeBaseModal } from './components/KnowledgeBaseModal'
import { SkillsModal } from './components/SkillsModal'
import { ImportCodeModal } from './components/ImportCodeModal'
import { normalizeNodeData } from './utils/blueprintToFlowData'
import { docLoaderNodeLabel, getDocLoader } from './utils/docLoaders'
import { validatePipeline } from './utils/pipelineValidation'
import { retestConnection } from './utils/connectionHealth'
import { refreshSecrets } from './utils/secrets'
import { browserProviderKeys } from './utils/providerKeys'
import { agentSystemPrompt, builtinAgentSpec, refreshAgentCatalog } from './utils/agentCatalog'
import type { BuiltinAgent } from './utils/agentCatalog'
import { columnsToJsonSchema } from './utils/syntheticSchema'

type PromptBuildMode = 'auto' | 'tool' | 'mcp' | 'pipeline'

type ToolDraft = {
  name: string
  icon: string
  description: string
  code: string
  config_keys: string[]
  packages?: string[]
}

type McpDraft = {
  name: string
  icon: string
  description: string
  transport: 'stdio' | 'sse' | 'http'
  command: string
  args: string[]
  env_vars: Record<string, string>
  url: string
  headers: Record<string, string>
}

type BuildGenerateResponse = {
  success: boolean
  intent: string
  blueprint?: {
    label?: string
    nodes?: Array<{
      id?: string
      type?: FlowNode['type']
      position?: { x?: number; y?: number }
      data?: Record<string, any>
    }>
    edges?: Array<{
      id?: string
      source?: string
      target?: string
    }>
    selected_node_id?: string
  }
  simulated?: boolean
  provider?: string
  model?: string
  message?: string
}

const LAST_PIPELINE_KEY = 'univ.lastPipelineId'

function FlowBuilder() {
  const { resolveApiKey } = useCredentials()
  const getProviderKeys = useCallback(() => browserProviderKeys(resolveApiKey), [resolveApiKey])
  const { scope, tenants, projects, setTenantId, setProjectId, refresh: refreshTenantContext } = useTenantContext()
  const { user, logout } = useAuth()
  const { executingNodeIds, isExecuting } = useExecution()
  // ── Flow state ─────────────────────────────────────────────────────────────
  const {
    nodes, setNodes, edges, setEdges,
    selectedNodeId, setSelectedNodeId,
    activeNode,
    loadFlow,
    deleteNode, updateNodeData,
    onNodesChange, onEdgesChange, onConnect, onNodeClick,
    screenToFlowPosition,
    undo, redo, canUndo, canRedo, copySelection, paste,
  } = useFlowManager()

  // ── App persistence ────────────────────────────────────────────────────────
  const {
    currentApp, setCurrentApp, savedAppsList, setSavedAppsList,
    appSaveStatus, loadApp, createApp, saveCurrentApp, publishApp, startEditing, renameApp, deleteApp,
  } = useAppManager(loadFlow, nodes, edges, setNodes, setEdges, setSelectedNodeId, getProviderKeys)

  const promptRenameApp = useCallback(async (app: AppRecord) => {
    const next = window.prompt('Rename pipeline', app.name)
    if (next === null || !next.trim() || next.trim() === app.name) return
    const error = await renameApp(app.id, next)
    if (error) window.alert(error)
  }, [renameApp])

  // ── Sidebar accordion + search state ──────────────────────────────────────
  const sidebar = useSidebarState()

  // ── Catalog / remote data ──────────────────────────────────────────────────
  const catalog = useCatalogData()

  
  // ── Top-level view / ops tab (mirrored in the URL, so a refresh stays put) ──
  const [initialLocation] = useState(() => parseAppUrl(window.location.search))
  const [topView, setTopView] = useState<TopView>(initialLocation.view)
  const [monitorTab, setMonitorTab] = useState<MonitorTab>(initialLocation.monitorTab)
  const [automationTab, setAutomationTab] = useState<AutomationTab>(initialLocation.automationTab)
  const [settingsTab, setSettingsTab] = useState<SettingsTab>(initialLocation.settingsTab)
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>(initialLocation.panel)
  const [docPage, setDocPage] = useState<string | null>(initialLocation.docPage)
  // Off until the boot fetch has picked a pipeline, so the URL's pipeline isn't overwritten first
  const [isUrlSynced, setIsUrlSynced] = useState(false)

  // ── Modal state ────────────────────────────────────────────────────────────
  const [isAppModalOpen, setIsAppModalOpen] = useState(false)
  const [isNewAppModalOpen, setIsNewAppModalOpen] = useState(false)
  const [newAppName, setNewAppName] = useState('')
  const [newAppDesc, setNewAppDesc] = useState('')
  const [isExportModalOpen, setIsExportModalOpen] = useState(false)
  const [isChatLinkModalOpen, setIsChatLinkModalOpen] = useState(false)
  const [isMarketplaceModalOpen, setIsMarketplaceModalOpen] = useState(false)
  const [isBottomConfigOpen, setIsBottomConfigOpen] = useState(true)
  const [validationStatusMsg, setValidationStatusMsg] = useState('')
  const [buildPrompt, setBuildPrompt] = useState('')
  const [buildMode, setBuildMode] = useState<PromptBuildMode>('auto')
  const [buildStatusMsg, setBuildStatusMsg] = useState('')
  const [isBuildingFromPrompt, setIsBuildingFromPrompt] = useState(false)
  const [toolDraftFromPrompt, setToolDraftFromPrompt] = useState<ToolDraft | null>(null)
  const [mcpDraftFromPrompt, setMcpDraftFromPrompt] = useState<McpDraft | null>(null)
  const [isImportCodeModalOpen, setIsImportCodeModalOpen] = useState(false)

  // ── Custom tool modal (managed here for fetchCustomTools callback) ──────────
  const fetchCustomTools = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/custom-tools`)
      if (res.ok) {
        const d = await res.json()
        sidebar.setCustomTools(d.tools ?? [])
      }
    } catch { /* backend not reachable */ }
  }, [sidebar])

  // ── Left panel resize ──────────────────────────────────────────────────────
  const [leftPanelWidth, setLeftPanelWidth] = useState(290)
  const [isLeftCollapsed, setIsLeftCollapsed] = useState(() => {
    try { return localStorage.getItem('univ.sidebarCollapsed') === '1' } catch { return false }
  })
  const toggleLeftCollapsed = useCallback(() => {
    setIsLeftCollapsed((prev) => {
      try { localStorage.setItem('univ.sidebarCollapsed', prev ? '0' : '1') } catch { /* storage unavailable */ }
      return !prev
    })
  }, [])
  const [rightPanelWidth, setRightPanelWidth] = useState(390)
  const isLeftResizing = useRef(false)
  const leftResizeStartX = useRef(0)
  const leftResizeStartWidth = useRef(290)
  const isRightResizing = useRef(false)
  const rightResizeStartX = useRef(0)
  const rightResizeStartWidth = useRef(390)

  const onLeftResizeMouseDown = useCallback((e: ReactMouseEvent) => {
    isLeftResizing.current = true
    leftResizeStartX.current = e.clientX
    leftResizeStartWidth.current = leftPanelWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [leftPanelWidth])

  const onRightResizeMouseDown = useCallback((e: ReactMouseEvent) => {
    isRightResizing.current = true
    rightResizeStartX.current = e.clientX
    rightResizeStartWidth.current = rightPanelWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [rightPanelWidth])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (isLeftResizing.current) {
        const delta = e.clientX - leftResizeStartX.current
        const next = Math.max(180, Math.min(500, leftResizeStartWidth.current + delta))
        setLeftPanelWidth(next)
      }
      if (isRightResizing.current) {
        const delta = e.clientX - rightResizeStartX.current
        const next = Math.max(320, Math.min(680, rightResizeStartWidth.current - delta))
        setRightPanelWidth(next)
      }
    }
    const onMouseUp = () => {
      if (!isLeftResizing.current && !isRightResizing.current) return
      isLeftResizing.current = false
      isRightResizing.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  // ── Boot ───────────────────────────────────────────────────────────────────
  useEffect(() => {
    void refreshSecrets()  // the vault list is module state; reload it for whoever just signed in
    // ?pipeline=<id> (a refresh, or the chat page's "Open in Pipesets" link) reopens that pipeline, when it's in this project;
    // off Build the URL has no pipeline, so fall back to the one last open in this browser
    let lastOpen: string | null = null
    try { lastOpen = localStorage.getItem(LAST_PIPELINE_KEY) } catch { /* storage unavailable */ }
    const wanted = initialLocation.pipelineId ?? lastOpen
    catalog.bootFetch((apps: AppRecord[]) => {
      setSavedAppsList(apps)
      const linked = wanted ? apps.find((a) => a.id === wanted) : undefined
      if (apps.length > 0) loadApp(linked ?? apps[0])
      else setIsNewAppModalOpen(true)
      setIsUrlSynced(true)
    })
    fetchCustomTools()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── URL ⇄ navigation state ─────────────────────────────────────────────────
  // Each view / tab / pipeline change is a history entry, so Back and Forward move between them.
  const currentAppId = currentApp?.id ?? null
  useEffect(() => {
    if (!currentAppId) return
    try { localStorage.setItem(LAST_PIPELINE_KEY, currentAppId) } catch { /* storage unavailable */ }
  }, [currentAppId])

  useEffect(() => {
    if (!isUrlSynced) return
    const search = buildAppUrl({ view: topView, monitorTab, automationTab, settingsTab, panel: rightPanelTab, pipelineId: currentAppId, docPage })
    if (search === window.location.search) return
    const firstWrite = !window.history.state?.pipesets
    window.history[firstWrite ? 'replaceState' : 'pushState']({ pipesets: true }, '', `${window.location.pathname}${search}${window.location.hash}`)
  }, [isUrlSynced, topView, monitorTab, automationTab, settingsTab, rightPanelTab, currentAppId, docPage])

  useEffect(() => {
    const onPopState = () => {
      const loc = parseAppUrl(window.location.search)
      setTopView(loc.view)
      setMonitorTab(loc.monitorTab)
      setAutomationTab(loc.automationTab)
      setSettingsTab(loc.settingsTab)
      setRightPanelTab(loc.panel)
      setDocPage(loc.docPage)
      const app = loc.pipelineId && loc.pipelineId !== currentAppId ? savedAppsList.find((a) => a.id === loc.pipelineId) : undefined
      if (app) loadApp(app)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [currentAppId, savedAppsList, loadApp])

  // "?" help links anywhere in the app open Docs at a section (components/docs/HelpLink.tsx)
  useEffect(() => {
    const onOpenDocs = (e: Event) => {
      const { page, section } = (e as CustomEvent<OpenDocsDetail>).detail
      const { pathname, search } = window.location
      window.history.replaceState(window.history.state, '', `${pathname}${search}${section ? `#${section}` : ''}`)
      setDocPage(page)
      setTopView('docs')
    }
    window.addEventListener(OPEN_DOCS_EVENT, onOpenDocs)
    return () => window.removeEventListener(OPEN_DOCS_EVENT, onOpenDocs)
  }, [])

  const addToolToToolkit = useCallback((toolkitNodeId: string, tool: ToolCatalogItem) => {
    setNodes((nds) =>
      nds.map((node) => {
        if (node.id !== toolkitNodeId) return node
        const data = node.data as ToolkitNodeData
        const existing = data.subTools || []
        if (existing.some((t) => t.toolId === tool.id)) return node
        const newSubTool: ToolkitSubTool = {
          toolId: tool.id,
          toolType: tool.type,
          label: tool.name,
          icon: tool.icon,
          description: tool.description,
          config: { ...tool.default_config },
        }
        return { ...node, data: { ...data, subTools: [...existing, newSubTool] } }
      })
    )
  }, [setNodes])

  // ── Keep canvas connection nodes in sync with live connection health ───────
  // Edits/re-tests update catalog.connections; mirror them onto the canvas so a
  // fixed connection turns green without reloading the page.
  useEffect(() => {
    const liveById = new Map(catalog.connections.map((c) => [c.id, c]))
    setNodes((nds) => {
      let changed = false
      const next = nds.map((node) => {
        if (node.type !== 'connection') return node
        const data = node.data as ConnectionNodeData
        const live = liveById.get(data.connection_id)
        if (!live) return node
        if (live.status === data.status && live.status_msg === (data.status_msg ?? '')
          && JSON.stringify(live.config) === JSON.stringify(data.config)) return node
        changed = true
        return { ...node, data: { ...data, config: { ...live.config }, status: live.status, status_msg: live.status_msg } }
      })
      return changed ? next : nds
    })
  }, [catalog.connections, setNodes])

  // While a connection on the canvas is failing, re-test it periodically and on
  // window focus, so starting the database is picked up automatically.
  const failingConnectionIds = useMemo(() => [...new Set(
    nodes
      .filter((n) => n.type === 'connection' && (n.data as ConnectionNodeData).status === 'error')
      .map((n) => (n.data as ConnectionNodeData).connection_id)
      .filter(Boolean),
  )].sort().join(','), [nodes])

  useEffect(() => {
    if (!failingConnectionIds) return
    const recheck = async () => {
      if (document.hidden) return
      await Promise.all(failingConnectionIds.split(',').map(retestConnection))
      catalog.fetchConnections()
    }
    const timer = setInterval(recheck, 15000)
    window.addEventListener('focus', recheck)
    return () => {
      clearInterval(timer)
      window.removeEventListener('focus', recheck)
    }
  }, [failingConnectionIds, catalog.fetchConnections])

  // ── Derived published lock ─────────────────────────────────────────────────
  const isPublished = currentApp?.status === 'published'
  const runValidation = useCallback(async () => {
    // Re-test connections live so a stale status can't pass (or fail) validation
    const connNodes = nodes.filter((n) => n.type === 'connection' && (n.data as ConnectionNodeData).connection_id)
    let currentNodes = nodes
    if (connNodes.length > 0) {
      setValidationStatusMsg('Testing connections…')
      const results = new Map(await Promise.all(
        connNodes.map(async (n) => [n.id, await retestConnection((n.data as ConnectionNodeData).connection_id)] as const),
      ))
      const patch = (nds: FlowNode[]) => nds.map((n) => {
        const health = results.get(n.id)
        return health ? { ...n, data: { ...n.data, ...health } } : n
      })
      currentNodes = patch(nodes)
      setNodes(patch)
      catalog.fetchConnections()
    }

    const validationIssues = validatePipeline(currentNodes, edges, resolveApiKey)
    const blockingCount = validationIssues.filter((i) => i.severity === 'error').length
    const warningCount = validationIssues.filter((i) => i.severity === 'warn').length

    if (validationIssues.length === 0) {
      setValidationStatusMsg('✓ Validation passed')
      setTimeout(() => setValidationStatusMsg(''), 3000)
      return
    }

    const firstIssueWithNode = validationIssues.find((i) => i.nodeId && i.severity === 'error')
      ?? validationIssues.find((i) => i.nodeId)
    if (firstIssueWithNode?.nodeId) {
      setSelectedNodeId(firstIssueWithNode.nodeId)
      setIsBottomConfigOpen(true)
    }

    setValidationStatusMsg(`${blockingCount} blocking, ${warningCount} warning(s)`)
    setTimeout(() => setValidationStatusMsg(''), 3500)
  }, [nodes, edges, resolveApiKey, setNodes, setSelectedNodeId, catalog.fetchConnections])

  const reloadScopedData = useCallback(() => {
    refreshTenantContext().then(() => {
      void refreshSecrets()  // the vault is per project
      catalog.bootFetch((apps: AppRecord[]) => {
        setSavedAppsList(apps)
        if (apps.length > 0) loadApp(apps[0])
        else {
          setNodes([])
          setEdges([])
          setSelectedNodeId(null)
        }
      })
      fetchCustomTools()
    })
  }, [catalog, fetchCustomTools, loadApp, refreshTenantContext, setEdges, setNodes, setSavedAppsList, setSelectedNodeId])

  // 📌 on a node: select it and show its Debug section (with the pin editor open when asked)
  const [debugEdit, setDebugEdit] = useState<{ nodeId: string; n: number } | null>(null)
  const openNodeDebug = useCallback((nodeId: string, editPin: boolean) => {
    setSelectedNodeId(nodeId)
    setIsBottomConfigOpen(true)
    setDebugEdit((prev) => (editPin ? { nodeId, n: (prev?.n ?? 0) + 1 } : null))
    requestAnimationFrame(() => document.querySelector('.node-debug-section')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
  }, [setSelectedNodeId])

  // ── Sync selection + delete callbacks into node data ──────────────────────
  useEffect(() => {
    setNodes((nds) =>
      nds.map((node) => ({
        ...node,
        data: {
          ...node.data,
          isSelected: node.id === selectedNodeId,
          // When published: no delete callback → nodes hide their ✕ button
          onDelete: isPublished ? undefined : () => deleteNode(node.id),
          // 🐞 Debug buttons on the node itself (breakpoint, pin); editor-only, not while published
          ...(DEBUGGABLE_NODE_TYPES.has(node.type ?? '') && !isPublished ? {
            onDebugUpdate: (fields: Record<string, unknown>) => updateNodeData(node.id, fields),
            onOpenDebug: (editPin: boolean) => openNodeDebug(node.id, editPin),
          } : { onDebugUpdate: undefined, onOpenDebug: undefined }),
          // A library skill's tools, for its readiness check (node and validation)
          ...(node.type === 'skill' ? {
            requiredTools: catalog.skills.find((s) => s.id === (node.data as { skill_id?: string }).skill_id)?.tool_ids,
          } : {}),
          ...(node.type === 'toolkit' ? {
            onDropTool: isPublished ? undefined : (tool: ToolCatalogItem) => addToolToToolkit(node.id, tool),
          } : {}),
        },
      }))
    )
  }, [selectedNodeId, deleteNode, setNodes, isPublished, addToolToToolkit, updateNodeData, openNodeDebug, catalog.skills])

  // ── Canvas shortcuts: undo/redo, copy/paste/duplicate ──────────────────────
  useEffect(() => {
    if (isPublished) return
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return
      // Only when the canvas (or nothing) has focus, so text fields and panels keep native shortcuts.
      const active = document.activeElement
      if (active && active !== document.body && !active.closest('.react-flow')) return
      const key = e.key.toLowerCase()
      if (key === 'z' || key === 'y') {
        e.preventDefault()
        if (key === 'y' || e.shiftKey) redo()
        else undo()
      } else if (key === 'c') {
        if (window.getSelection()?.toString()) return   // copying page text
        if (copySelection()) e.preventDefault()
      } else if (key === 'v') {
        if (paste()) e.preventDefault()
      } else if (key === 'd') {
        e.preventDefault()                               // browser bookmark otherwise
        if (copySelection()) paste()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isPublished, undo, redo, copySelection, paste])

  // ── Drag helpers ───────────────────────────────────────────────────────────
  const toggleProviderGroup = useCallback((id: string) => {
    sidebar.setCollapsedProviders((prev) => ({ ...prev, [id]: !(prev[id] ?? true) }))
  }, [sidebar])

  const onDragStartLlm = useCallback((e: DragEvent<HTMLDivElement>, providerId: string, modelName: string) => {
    e.dataTransfer.setData('application/univ-type', 'llm')
    e.dataTransfer.setData('application/univ-provider', providerId)
    e.dataTransfer.setData('application/univ-model', modelName)
    e.dataTransfer.effectAllowed = 'move'
  }, [])

  const onDragStartTool = useCallback((e: DragEvent<HTMLDivElement>, tool: ToolCatalogItem) => {
    e.dataTransfer.setData('application/univ-type', 'tool')
    e.dataTransfer.setData('application/univ-tool-data', JSON.stringify(tool))
    e.dataTransfer.effectAllowed = 'move'
  }, [])

  const onDragStartToolkit = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.dataTransfer.setData('application/univ-type', 'toolkit')
    e.dataTransfer.effectAllowed = 'move'
  }, [])

  const onDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    const dropType = e.dataTransfer.getData('application/univ-type')
    const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })
    const newNodeId = `node-${Date.now()}`

    let newNode: FlowNode | null = null

    if (dropType === 'doc_loader') {
      const loaderType = (e.dataTransfer.getData('application/univ-loader-type') || 'pdf') as DocLoaderNodeData['loader_type']
      const customDef = getDocLoader(loaderType)?.custom ? getDocLoader(loaderType) : undefined
      newNode = { id: newNodeId, type: 'doc_loader', position, data: {
        label: docLoaderNodeLabel(loaderType), loader_type: loaderType,
        ...(customDef ? { loader_class: customDef.loaderClass, loader_kwargs: customDef.loaderKwargs } : {}),
        source: '', chunk_strategy: 'fixed', isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'text_splitter') {
      const splitterType = (e.dataTransfer.getData('application/univ-splitter-type') || 'recursive_character') as TextSplitterNodeData['splitter_type']
      const splitterLabels: Record<string, string> = { recursive_character: 'Recursive Splitter', token: 'Token Splitter', markdown: 'Markdown Splitter' }
      newNode = { id: newNodeId, type: 'text_splitter', position, data: {
        label: splitterLabels[splitterType] ?? 'Text Splitter', splitter_type: splitterType,
        chunk_size: 512, chunk_overlap: 50, isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'embedding') {
      const embProvider = (e.dataTransfer.getData('application/univ-emb-provider') || 'openai') as EmbeddingNodeData['provider']
      const embModel = e.dataTransfer.getData('application/univ-emb-model') || 'text-embedding-3-small'
      const providerLabels: Record<string, string> = { openai: 'OpenAI Embedding', local: 'Local Embedding' }
      newNode = { id: newNodeId, type: 'embedding', position, data: {
        label: providerLabels[embProvider] ?? 'Embedding Node', provider: embProvider,
        model: embModel, api_key: '', isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'vector_store') {
      const storeType = (e.dataTransfer.getData('application/univ-store-type') || 'local') as VectorStoreNodeData['store_type']
      const storeLabels: Record<string, string> = { local: 'Local Vector Store', pgvector: 'pgvector Store' }
      newNode = { id: newNodeId, type: 'vector_store', position, data: {
        label: storeLabels[storeType] ?? 'Vector Store', store_type: storeType,
        collection_name: 'my_documents', connection_string: '', top_k: 5,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'retriever') {
      const searchType = (e.dataTransfer.getData('application/univ-retriever-type') || 'similarity') as 'similarity' | 'mmr' | 'bm25_hybrid'
      const retrieverLabels: Record<string, string> = { similarity: 'Similarity Retriever', mmr: 'MMR Retriever', bm25_hybrid: 'BM25 Hybrid Retriever' }
      newNode = { id: newNodeId, type: 'retriever', position, data: {
        label: retrieverLabels[searchType] ?? 'Retriever', search_type: searchType,
        collection_name: 'my_documents', top_k: 5, score_threshold: 0,
        rerank: false, embedding_provider: 'local',
        embedding_model: 'sentence-transformers/all-MiniLM-L6-v2', embedding_api_key: '',
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'master_agent') {
      const strategy = (e.dataTransfer.getData('application/univ-agent-strategy') || 'sequential') as 'sequential' | 'parallel' | 'dynamic'
      newNode = { id: newNodeId, type: 'master_agent', position, data: {
        label: 'Master Agent', provider: 'openai', model: 'gpt-4o', api_key: '',
        timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
        fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '', base_url: '',
        goal: '', max_steps: 5, strategy,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'child_agent') {
      const role = e.dataTransfer.getData('application/univ-agent-role') || 'Researcher'
      const agentKind = e.dataTransfer.getData('application/univ-agent-kind')
      const isExternal = agentKind === 'external'
      const isPipelineChild = agentKind === 'pipeline'
      newNode = { id: newNodeId, type: 'child_agent', position, data: {
        label: isExternal ? 'External Agent' : isPipelineChild ? 'Pipeline Agent' : `${role} Agent`, master_id: '',
        role: isPipelineChild ? 'Pipeline' : role,
        provider: 'openai', model: isExternal ? '' : 'gpt-4o', api_key: '',
        timeout_ms: isPipelineChild ? 120000 : 45000, max_retries: 1, retry_backoff_ms: 500,
        fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '', base_url: '',
        allowed_tool_ids: [],
        system_prompt: (isExternal || isPipelineChild) ? '' : agentSystemPrompt(role),
        ...(e.dataTransfer.getData('application/univ-agent-builtin') ? { builtin_agent_id: e.dataTransfer.getData('application/univ-agent-builtin') } : {}),
        ...(isExternal ? {
          kind: 'external', endpoint_url: '', protocol: 'openai', auth_type: 'bearer',
          auth_header: 'X-API-Key', request_template: '', response_path: '',
        } : {}),
        ...(isPipelineChild ? { kind: 'pipeline', app_id: '', app_name: '', app_version: 0 } : {}),
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'saved_agent' || dropType === 'builtin_agent') {
      // A saved agent, or a tool-backed built-in: the child plus its tool and skill nodes, wired up
      const raw = e.dataTransfer.getData(dropType === 'saved_agent' ? 'application/univ-saved-agent' : 'application/univ-builtin-agent')
      if (!raw) return
      let made
      if (dropType === 'saved_agent') {
        made = instantiateSavedAgent(JSON.parse(raw) as SavedAgent, position, newNodeId)
      } else {
        const agent = JSON.parse(raw) as BuiltinAgent
        const toolItems = new Map(catalog.toolCategories.flatMap((c) => c.tools).map((t) => [t.id, t]))
        made = instantiateSpec(builtinAgentSpec(agent, toolItems), position, newNodeId,
          { label: `${agent.name} Agent`, builtin_agent_id: agent.id })
      }
      const withCallbacks = made.nodes.map((n) => ({
        ...n,
        data: {
          ...n.data, onDelete: () => deleteNode(n.id),
          ...(n.type === 'toolkit' ? { onDropTool: (tool: ToolCatalogItem) => addToolToToolkit(n.id, tool) } : {}),
        },
      }) as FlowNode)
      recordRecentNode(String(made.nodes[0].data.label ?? 'Saved agent'), 'child_agent', e.dataTransfer)
      setNodes((nds) => [...nds, ...withCallbacks])
      setEdges((eds) => [...eds, ...made.edges])
      setSelectedNodeId(newNodeId)
      setIsBottomConfigOpen(true)
      return
    } else if (dropType === 'cache') {
      const rawScope = (e.dataTransfer.getData('application/univ-cache-scope') || 'prompt') as CacheNodeData['scope']
      const rawTtl = parseInt(e.dataTransfer.getData('application/univ-cache-ttl') || '3600', 10)
      const rawMax = parseInt(e.dataTransfer.getData('application/univ-cache-max') || '500', 10)
      const scopeLabels: Record<string, string> = { prompt: 'Prompt Cache', model: 'Model Cache', strict: 'Strict Cache' }
      newNode = { id: newNodeId, type: 'cache', position, data: {
        label: scopeLabels[rawScope] ?? 'Cache Node', scope: rawScope,
        ttl_seconds: rawTtl, max_size: rawMax, isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'memory') {
      const rawStrategy = (e.dataTransfer.getData('application/univ-memory-strategy') || 'sliding_window') as MemoryNodeData['strategy']
      const rawBudget = parseInt(e.dataTransfer.getData('application/univ-memory-budget') || '4096', 10)
      const strategyLabels: Record<string, string> = { sliding_window: 'Sliding Window Memory', summarize: 'Summarize Memory', last_k: 'Last K Memory' }
      newNode = { id: newNodeId, type: 'memory', position, data: {
        label: strategyLabels[rawStrategy] ?? 'Memory Node', strategy: rawStrategy,
        token_budget: rawBudget, session_id: `session-${newNodeId}`, session_ttl_hours: 24,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'knowledge_base') {
      const rawKbData = e.dataTransfer.getData('application/univ-kb-data')
      if (!rawKbData) return
      const kbItem: KnowledgeBaseRecord = JSON.parse(rawKbData)
      newNode = { id: newNodeId, type: 'knowledge_base', position, data: {
        label: kbItem.name, kb_id: kbItem.id, icon: kbItem.icon,
        description: kbItem.description, chunk_count: kbItem.chunk_count,
        embedding_provider: kbItem.embedding_provider, embedding_model: kbItem.embedding_model,
        top_k: 4, score_threshold: 0.0,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'connection') {
      const rawConnData = e.dataTransfer.getData('application/univ-connection-data')
      if (!rawConnData) return
      const connItem: ConnectionRecord = JSON.parse(rawConnData)
      newNode = { id: newNodeId, type: 'connection', position, data: {
        label: connItem.name, connection_id: connItem.id, connection_type: connItem.type,
        icon: connItem.icon, description: connItem.description, config: { ...connItem.config },
        status: connItem.status, status_msg: connItem.status_msg,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'skill') {
      const rawSkillData = e.dataTransfer.getData('application/univ-skill-data')
      if (!rawSkillData) return
      const skillItem: SkillRecord = JSON.parse(rawSkillData)
      newNode = { id: newNodeId, type: 'skill', position, data: {
        label: skillItem.name, skill_id: skillItem.id, icon: skillItem.icon || '⚡',
        description: skillItem.description || '', instructions: skillItem.instructions || '',
        category: skillItem.category || 'general', tool_ids: skillItem.tool_ids || [], tags: skillItem.tags || [],
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'gateway') {
      const kind = (e.dataTransfer.getData('application/univ-gateway-kind') || 'condition') as import('./types').GatewayKind
      const kindLabels: Record<string, string> = {
        condition: 'Condition Gateway',
        merge:     'Merge Gateway',
        split:     'Split Gateway',
        loop:      'Loop Gateway',
      }
      newNode = { id: newNodeId, type: 'gateway', position, data: {
        label: kindLabels[kind] ?? 'Gateway',
        kind,
        condition_expr: kind === 'condition' ? '' : undefined,
        true_label:     kind === 'condition' ? 'Yes' : undefined,
        false_label:    kind === 'condition' ? 'No'  : undefined,
        branch_count:   kind === 'split'     ? 2    : undefined,
        max_iterations: kind === 'loop'      ? 3    : undefined,
        loop_condition: kind === 'loop'      ? ''   : undefined,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'start') {
      newNode = { id: newNodeId, type: 'start', position, data: {
        label: 'Start', isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'stop') {
      newNode = { id: newNodeId, type: 'stop', position, data: {
        label: 'Stop', isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'toolkit') {
      newNode = { id: newNodeId, type: 'toolkit', position, data: {
        label: 'My Toolkit', toolkitId: `toolkit-${newNodeId}`, icon: '🗂️',
        description: 'A custom toolkit. Drop tool cards onto this node to add sub-tools.',
        subTools: [], isSelected: true, onDelete: () => deleteNode(newNodeId),
        onDropTool: (tool: ToolCatalogItem) => addToolToToolkit(newNodeId, tool),
      }}
    } else if (dropType === 'tool') {
      const rawToolData = e.dataTransfer.getData('application/univ-tool-data')
      if (!rawToolData) return
      const toolItem: ToolCatalogItem = JSON.parse(rawToolData)
      newNode = { id: newNodeId, type: 'tool', position, data: {
        label: toolItem.name, toolId: toolItem.id, toolType: toolItem.type,
        icon: toolItem.icon, description: toolItem.description,
        config: { ...toolItem.default_config }, isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'reranker') {
      const rerankerType = (e.dataTransfer.getData('application/univ-reranker-type') || 'cohere') as import('./types').RerankerNodeData['reranker_type']
      const rerankerModel = e.dataTransfer.getData('application/univ-reranker-model') || 'rerank-english-v3.0'
      const rerankerTopN = parseInt(e.dataTransfer.getData('application/univ-reranker-topn') || '5', 10)
      const rerankerLabels: Record<string, string> = { cohere: 'Cohere', cross_encoder: 'CrossEncoder', flashrank: 'FlashRank', bge: 'BGE Reranker' }
      newNode = { id: newNodeId, type: 'reranker', position, data: {
        label: `${rerankerLabels[rerankerType] ?? rerankerType} Reranker`,
        reranker_type: rerankerType, model: rerankerModel, api_key: '', top_n: rerankerTopN,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'human_gate') {
      const gateType = (e.dataTransfer.getData('application/univ-gate-type') || 'approval') as import('./types').HumanGateNodeData['gate_type']
      const timeoutHours = parseInt(e.dataTransfer.getData('application/univ-gate-timeout') || '24', 10)
      const gateLabels: Record<string, string> = { approval: 'Approval Gate', edit: 'Edit Gate', review: 'Review Gate' }
      newNode = { id: newNodeId, type: 'human_gate', position, data: {
        label: gateLabels[gateType] ?? 'Human Gate',
        gate_type: gateType, prompt_message: '', timeout_hours: timeoutHours, on_timeout: 'reject',
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'checkpointer') {
      const mode = e.dataTransfer.getData('application/univ-checkpoint-mode') || 'resume'
      newNode = { id: newNodeId, type: 'checkpointer', position, data: {
        label: 'Checkpointer',
        save_steps: mode !== 'off', restore_on_resume: mode === 'resume',
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'wf_step') {
      const stepType = (e.dataTransfer.getData('application/univ-wf-step-type') || 'ask') as import('./types').WorkflowStepType
      const stepLabels: Record<string, string> = { ask: 'Ask User', choice: 'Choose Option', confirm: 'Confirm', tool_call: 'Call Tool', message: 'Show Message' }
      newNode = { id: newNodeId, type: 'wf_step', position, data: {
        label: stepLabels[stepType] ?? 'Workflow Step',
        step_type: stepType, prompt: '', variable: '', input_kind: 'text',
        options_source: '', option_label_field: '', option_value_field: '', tool_id: '', tool_input: '',
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'output_parser') {
      const parserType = (e.dataTransfer.getData('application/univ-parser-type') || 'json') as import('./types').OutputParserNodeData['parser_type']
      const parserLabels: Record<string, string> = { json: 'JSON Parser', pydantic: 'Pydantic Parser', regex: 'Regex Parser', csv: 'CSV Parser', datetime: 'DateTime Parser', enum: 'Enum Parser' }
      newNode = { id: newNodeId, type: 'output_parser', position, data: {
        label: parserLabels[parserType] ?? 'Output Parser',
        parser_type: parserType, schema_json: '', strict: false,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'middleware') {
      const mwType = (e.dataTransfer.getData('application/univ-mw-type') || 'content_moderation') as import('./types').MiddlewareNodeData['middleware_type']
      const mwLabels: Record<string, string> = { content_moderation: 'Content Moderation', cost_tracker: 'Cost Tracker', rate_limiter: 'Rate Limiter', prompt_injection: 'Prompt Injection', grounding: 'Grounding Check', custom_rule: 'Custom Rule', custom_pattern: 'Custom Pattern' }
      newNode = { id: newNodeId, type: 'middleware', position, data: {
        label: mwLabels[mwType] ?? 'Guardrail',
        middleware_type: mwType, config: {}, enabled: true,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else if (dropType === 'synthetic_data') {
      const preset = e.dataTransfer.getData('application/univ-synth-preset') || 'synth-generate'
      const customLabel = e.dataTransfer.getData('application/univ-label').trim()
      const defaults: Record<string, Pick<SyntheticDataNodeData, 'dataset_name' | 'prompt_instructions' | 'columns'>> = {
        'synth-schema': {
          dataset_name: 'customer_profile_seed',
          prompt_instructions: 'Design a strong schema first, then generate data from that schema.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'customer_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'age', type: 'integer', nullable: false, unique: false, min: 18, max: 80 },
            { id: `col-${newNodeId}-3`, name: 'segment', type: 'category', nullable: false, unique: false, values: 'gold,silver,bronze' },
          ],
        },
        'synth-generate': {
          dataset_name: 'synthetic_dataset',
          prompt_instructions: 'Generate realistic records with balanced category distribution and include edge cases.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'customer_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'age', type: 'integer', nullable: false, unique: false, min: 18, max: 80 },
            { id: `col-${newNodeId}-3`, name: 'segment', type: 'category', nullable: false, unique: false, values: 'gold,silver,bronze' },
          ],
        },
        'synth-validate': {
          dataset_name: 'synthetic_quality_check',
          prompt_instructions: 'Validate data quality against schema and report coverage gaps.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'customer_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'age', type: 'integer', nullable: false, unique: false, min: 18, max: 80 },
            { id: `col-${newNodeId}-3`, name: 'segment', type: 'category', nullable: false, unique: false, values: 'gold,silver,bronze' },
          ],
        },
        'synth-salesforce': {
          dataset_name: 'salesforce_records',
          prompt_instructions: 'Generate realistic Salesforce-style CRM data with coherent Account, Contact, Opportunity, and Lead attributes.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'sf_id', type: 'string', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'account_name', type: 'string', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'opportunity_amount', type: 'number', nullable: false, unique: false, min: 1000, max: 500000 },
            { id: `col-${newNodeId}-4`, name: 'stage', type: 'category', nullable: false, unique: false, values: 'Prospecting,Negotiation,Closed Won,Closed Lost' },
          ],
        },
        'synth-pii': {
          dataset_name: 'pii_profiles',
          prompt_instructions: 'Generate sensitive personal profile data useful for masking, tokenization, and privacy controls testing.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'person_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'full_name', type: 'string', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'email', type: 'email', nullable: false, unique: true },
            { id: `col-${newNodeId}-4`, name: 'ssn_masked', type: 'string', nullable: false, unique: false },
          ],
        },
        'synth-orders': {
          dataset_name: 'orders_dataset',
          prompt_instructions: 'Generate ecommerce orders with realistic totals, statuses, timestamps, and fulfillment patterns.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'order_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'customer_id', type: 'uuid', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'order_total', type: 'number', nullable: false, unique: false, min: 5, max: 5000 },
            { id: `col-${newNodeId}-4`, name: 'order_status', type: 'category', nullable: false, unique: false, values: 'pending,paid,shipped,delivered,returned,cancelled' },
          ],
        },
        'synth-sales': {
          dataset_name: 'sales_transactions',
          prompt_instructions: 'Generate sales transaction data suitable for BI dashboards with realistic seasonality and product mix.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'txn_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'region', type: 'category', nullable: false, unique: false, values: 'NA,EMEA,APAC,LATAM' },
            { id: `col-${newNodeId}-3`, name: 'revenue', type: 'number', nullable: false, unique: false, min: 50, max: 100000 },
            { id: `col-${newNodeId}-4`, name: 'units_sold', type: 'integer', nullable: false, unique: false, min: 1, max: 500 },
          ],
        },
        'synth-hr': {
          dataset_name: 'hr_employee_data',
          prompt_instructions: 'Generate HR records across departments, seniority bands, compensation, tenure, and performance.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'employee_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'department', type: 'category', nullable: false, unique: false, values: 'Engineering,Sales,Marketing,HR,Finance,Support' },
            { id: `col-${newNodeId}-3`, name: 'annual_salary', type: 'number', nullable: false, unique: false, min: 35000, max: 280000 },
            { id: `col-${newNodeId}-4`, name: 'years_at_company', type: 'integer', nullable: false, unique: false, min: 0, max: 40 },
          ],
        },
        'synth-graphdb': {
          dataset_name: 'graph_entities_edges',
          prompt_instructions: 'Generate graph-oriented data with node IDs, edge IDs, relation types, and connected entity metadata.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'edge_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'source_node_id', type: 'uuid', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'target_node_id', type: 'uuid', nullable: false, unique: false },
            { id: `col-${newNodeId}-4`, name: 'relation_type', type: 'category', nullable: false, unique: false, values: 'FRIEND_OF,PURCHASED,WORKS_WITH,BELONGS_TO,LINKS_TO' },
          ],
        },
        'synth-finance': {
          dataset_name: 'finance_ledger_entries',
          prompt_instructions: 'Generate finance and accounting records including postings, balances, and payment status transitions.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'entry_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'account_code', type: 'string', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'amount', type: 'number', nullable: false, unique: false, min: -500000, max: 500000 },
            { id: `col-${newNodeId}-4`, name: 'currency', type: 'category', nullable: false, unique: false, values: 'USD,EUR,GBP,INR' },
          ],
        },
        'synth-healthcare': {
          dataset_name: 'healthcare_visits',
          prompt_instructions: 'Generate realistic healthcare interactions with patient demographics, encounter metadata, and coded outcomes.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'patient_id', type: 'uuid', nullable: false, unique: false },
            { id: `col-${newNodeId}-2`, name: 'visit_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-3`, name: 'age', type: 'integer', nullable: false, unique: false, min: 0, max: 100 },
            { id: `col-${newNodeId}-4`, name: 'diagnosis_code', type: 'string', nullable: false, unique: false },
          ],
        },
        'synth-marketing': {
          dataset_name: 'marketing_campaign_performance',
          prompt_instructions: 'Generate campaign metrics with channels, spend, impressions, clicks and conversions.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'campaign_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'channel', type: 'category', nullable: false, unique: false, values: 'search,social,email,display,affiliate' },
            { id: `col-${newNodeId}-3`, name: 'spend', type: 'number', nullable: false, unique: false, min: 10, max: 250000 },
            { id: `col-${newNodeId}-4`, name: 'conversions', type: 'integer', nullable: false, unique: false, min: 0, max: 20000 },
          ],
        },
        'synth-support': {
          dataset_name: 'support_tickets',
          prompt_instructions: 'Generate customer support tickets with severity, SLA windows, and closure outcomes.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'ticket_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'priority', type: 'category', nullable: false, unique: false, values: 'low,medium,high,urgent' },
            { id: `col-${newNodeId}-3`, name: 'status', type: 'category', nullable: false, unique: false, values: 'open,pending,resolved,closed' },
            { id: `col-${newNodeId}-4`, name: 'resolution_hours', type: 'number', nullable: false, unique: false, min: 0.1, max: 720 },
          ],
        },
        'synth-supply-chain': {
          dataset_name: 'supply_chain_movements',
          prompt_instructions: 'Generate supply chain movements across suppliers, warehouses, and logistics routes.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'shipment_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'warehouse', type: 'string', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'units', type: 'integer', nullable: false, unique: false, min: 1, max: 50000 },
            { id: `col-${newNodeId}-4`, name: 'shipment_status', type: 'category', nullable: false, unique: false, values: 'created,in_transit,received,delayed,damaged' },
          ],
        },
        'synth-iot': {
          dataset_name: 'iot_device_telemetry',
          prompt_instructions: 'Generate IoT telemetry readings with realistic ranges, drift and occasional anomalies.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'device_id', type: 'uuid', nullable: false, unique: false },
            { id: `col-${newNodeId}-2`, name: 'reading_ts', type: 'datetime', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'temperature_c', type: 'number', nullable: false, unique: false, min: -40, max: 120 },
            { id: `col-${newNodeId}-4`, name: 'battery_pct', type: 'number', nullable: false, unique: false, min: 0, max: 100 },
          ],
        },
        'synth-fraud': {
          dataset_name: 'fraud_risk_events',
          prompt_instructions: 'Generate transaction risk events with normal behavior mixed with suspicious patterns.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'event_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'transaction_amount', type: 'number', nullable: false, unique: false, min: 1, max: 100000 },
            { id: `col-${newNodeId}-3`, name: 'risk_score', type: 'number', nullable: false, unique: false, min: 0, max: 1 },
            { id: `col-${newNodeId}-4`, name: 'is_fraud', type: 'boolean', nullable: false, unique: false },
          ],
        },
        'synth-log-events': {
          dataset_name: 'application_log_events',
          prompt_instructions: 'Generate structured application logs across services, severity levels, and request traces.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'event_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'service', type: 'string', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'level', type: 'category', nullable: false, unique: false, values: 'DEBUG,INFO,WARN,ERROR' },
            { id: `col-${newNodeId}-4`, name: 'message', type: 'string', nullable: false, unique: false },
          ],
        },
        'synth-retail': {
          dataset_name: 'retail_pos_sales',
          prompt_instructions: 'Generate in-store retail POS data with basket value, SKUs, discounts, and payment mix.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'receipt_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'store_id', type: 'string', nullable: false, unique: false },
            { id: `col-${newNodeId}-3`, name: 'basket_total', type: 'number', nullable: false, unique: false, min: 1, max: 5000 },
            { id: `col-${newNodeId}-4`, name: 'payment_method', type: 'category', nullable: false, unique: false, values: 'cash,card,wallet,credit' },
          ],
        },
        'synth-public-sector': {
          dataset_name: 'public_service_cases',
          prompt_instructions: 'Generate public service case records with departments, service requests, and completion SLAs.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'case_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'department', type: 'category', nullable: false, unique: false, values: 'transport,utilities,permits,health,safety' },
            { id: `col-${newNodeId}-3`, name: 'priority', type: 'category', nullable: false, unique: false, values: 'low,medium,high' },
            { id: `col-${newNodeId}-4`, name: 'resolution_days', type: 'integer', nullable: false, unique: false, min: 0, max: 180 },
          ],
        },
        'synth-qa-testing': {
          dataset_name: 'qa_test_fixtures',
          prompt_instructions: 'Generate QA-ready test fixtures with deterministic edge cases, nulls, and boundary distributions.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'fixture_id', type: 'uuid', nullable: false, unique: true },
            { id: `col-${newNodeId}-2`, name: 'scenario', type: 'category', nullable: false, unique: false, values: 'happy_path,boundary,invalid,missing_field' },
            { id: `col-${newNodeId}-3`, name: 'expected_valid', type: 'boolean', nullable: false, unique: false },
            { id: `col-${newNodeId}-4`, name: 'score', type: 'number', nullable: true, unique: false, min: 0, max: 1 },
          ],
        },
        'synth-csv-upload': {
          dataset_name: 'uploaded_csv_dataset',
          prompt_instructions: 'Upload a CSV sample in the config panel to infer schema, then generate realistic synthetic expansions.',
          columns: [
            { id: `col-${newNodeId}-1`, name: 'column_1', type: 'string', nullable: false, unique: false },
            { id: `col-${newNodeId}-2`, name: 'column_2', type: 'string', nullable: true, unique: false },
            { id: `col-${newNodeId}-3`, name: 'column_3', type: 'string', nullable: true, unique: false },
          ],
        },
      }
      const chosen = defaults[preset] ?? defaults['synth-generate']
      const schemaJson = columnsToJsonSchema(chosen.columns)
      newNode = { id: newNodeId, type: 'synthetic_data', position, data: {
        label: customLabel || 'Synthetic Data Generator',
        dataset_name: chosen.dataset_name,
        row_count: 100,
        output_format: 'jsonl',
        schema_mode: 'manual',
        schema_json: schemaJson,
        columns: chosen.columns,
        locale: 'en_US',
        seed: 42,
        strict_schema: true,
        include_edge_cases: true,
        strict_routing: false,
        prompt_instructions: chosen.prompt_instructions,
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    } else {
      const provider = e.dataTransfer.getData('application/univ-provider') || 'openai'
      const model = e.dataTransfer.getData('application/univ-model') || 'gpt-4o'
      const customLabel = e.dataTransfer.getData('application/univ-label').trim()
      const customSystemPrompt = e.dataTransfer.getData('application/univ-system-prompt')
      const customTemperatureRaw = e.dataTransfer.getData('application/univ-temperature')
      const customMaxTokensRaw = e.dataTransfer.getData('application/univ-max-tokens')
      const parsedTemp = Number.parseFloat(customTemperatureRaw)
      const parsedMaxTokens = Number.parseInt(customMaxTokensRaw, 10)
      newNode = { id: newNodeId, type: 'llm', position, data: {
        label: customLabel || `${model.toUpperCase()} Node`, provider, model,
        temperature: Number.isFinite(parsedTemp) ? parsedTemp : 0.7,
        max_tokens: Number.isFinite(parsedMaxTokens) ? parsedMaxTokens : 1024,
        top_p: 1.0,
        api_key: '', system_prompt: customSystemPrompt || 'You are a helpful and concise AI assistant.', base_url: '',
        timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
        fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '',
        isSelected: true, onDelete: () => deleteNode(newNodeId),
      }}
    }

    if (newNode) {
      recordRecentNode(String(newNode.data.label ?? newNode.type), newNode.type ?? '', e.dataTransfer)
      setNodes((nds) => [...nds, newNode!])
      setSelectedNodeId(newNodeId)
      setIsBottomConfigOpen(true)
    }
  }, [screenToFlowPosition, deleteNode, setNodes, setEdges, setSelectedNodeId, addToolToToolkit, catalog.toolCategories])

  // ── App modal handlers ─────────────────────────────────────────────────────
  const [isCreatingApp, setIsCreatingApp] = useState(false)
  const handleCreateNewApp = async (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    if (!newAppName.trim() || isCreatingApp) return
    setIsCreatingApp(true)
    await createApp(newAppName, newAppDesc)
    setNewAppName('')
    setNewAppDesc('')
    setIsCreatingApp(false)
    setIsNewAppModalOpen(false)
  }

  // ── Open a pipeline from the Operations view ───────────────────────────────
  const handleOpenPipeline = (appId: string) => {
    const app = savedAppsList.find((a) => a.id === appId)
    if (app) { loadApp(app); setTopView('build') }
  }

  // Apps imported from the marketplace aren't in savedAppsList yet, so fetch by id
  const openAppById = async (appId: string) => {
    const res = await fetch(`${API_BASE}/api/apps/${appId}`)
    if (!res.ok) return
    loadApp(await res.json())
    setTopView('build')
  }

  const hydrateGeneratedBlueprint = useCallback((blueprint: BuildGenerateResponse['blueprint']) => {
    const rawNodes = Array.isArray(blueprint?.nodes) ? blueprint!.nodes! : []
    const rawEdges = Array.isArray(blueprint?.edges) ? blueprint!.edges! : []
    if (rawNodes.length === 0) return null

    const ts = Date.now()
    const idMap = new Map<string, string>()

    const mappedNodes: FlowNode[] = rawNodes.map((n, idx) => {
      const originalId = (n.id || `gen-node-${idx}`).trim()
      const mappedId = `node-${ts}-${idx}`
      idMap.set(originalId, mappedId)

      const rawType = n.type || 'llm'
      const nodeType = rawType as FlowNode['type']
      const baseData = normalizeNodeData(rawType, { ...(n.data || {}) })
      const shared = {
        ...baseData,
        isSelected: false,
        onDelete: () => deleteNode(mappedId),
      }

      let data: any = shared
      if (nodeType === 'toolkit') {
        data = {
          ...shared,
          subTools: Array.isArray(baseData.subTools) ? baseData.subTools : [],
          onDropTool: (tool: ToolCatalogItem) => addToolToToolkit(mappedId, tool),
        }
      }

      return {
        id: mappedId,
        type: nodeType,
        position: {
          x: Number(n.position?.x ?? (220 + idx * 40)),
          y: Number(n.position?.y ?? (180 + idx * 28)),
        },
        data,
      } as FlowNode
    })

    const mappedEdges = rawEdges
      .map((e, idx) => {
        const src = e.source ? idMap.get(e.source) : undefined
        const tgt = e.target ? idMap.get(e.target) : undefined
        if (!src || !tgt) return null
        return {
          id: e.id || `edge-${ts}-${idx}`,
          source: src,
          target: tgt,
        }
      })
      .filter(Boolean) as Array<{ id: string; source: string; target: string }>

    const selectedRaw = blueprint?.selected_node_id
    const selectedId = selectedRaw && idMap.get(selectedRaw) ? idMap.get(selectedRaw)! : mappedNodes[0].id
    const selectedNodes = mappedNodes.map((n) => ({ ...n, data: { ...n.data, isSelected: n.id === selectedId } }))

    return {
      nodes: selectedNodes,
      edges: mappedEdges,
      selectedNodeId: selectedId,
    }
  }, [addToolToToolkit, deleteNode])

  const detectBuildIntent = useCallback((promptText: string, mode: PromptBuildMode): Exclude<PromptBuildMode, 'auto'> => {
    if (mode !== 'auto') return mode
    const s = promptText.toLowerCase()
    const mcpScore = Number(/\bmcp\b|server|stdio|sse|transport|endpoint/.test(s))
    const toolScore = Number(/\btool\b|function|python|script|api|connector/.test(s))
    const pipelineScore = Number(/pipeline|workflow|flow|agent|rag|orchestrat|sequence|multi[ -]?step/.test(s))

    if (mcpScore >= toolScore && mcpScore >= pipelineScore && mcpScore > 0) return 'mcp'
    if (toolScore >= pipelineScore && toolScore > 0) return 'tool'
    return 'pipeline'
  }, [])

  const scaffoldPipelineFromPrompt = useCallback((promptText: string) => {
    const s = promptText.toLowerCase()
    const base = Date.now()
    const mkId = (suffix: string) => `node-${base}-${suffix}`
    const edgeId = (source: string, target: string) => `edge-${source}-${target}`

    const createNode = (id: string, type: FlowNode['type'], x: number, y: number, data: FlowNode['data']): FlowNode => ({
      id,
      type,
      position: { x, y },
      data,
    })

    const isRag = /\brag\b|retriev|embed|vector|document|knowledge base|kb|index/.test(s)
    const isAgent = /multi[ -]?agent|master agent|child agent|research|review|delegate|planner/.test(s)

    if (isAgent) {
      const startId = mkId('start')
      const masterId = mkId('master')
      const childResearchId = mkId('child-research')
      const childWriterId = mkId('child-writer')
      const childReviewerId = mkId('child-reviewer')
      const stopId = mkId('stop')

      const nextNodes: FlowNode[] = [
        createNode(startId, 'start', 220, 280, {
          label: 'Start', isSelected: false, onDelete: () => deleteNode(startId),
        }),
        createNode(masterId, 'master_agent', 500, 250, {
          label: 'Master Agent', provider: 'openai', model: 'gpt-4o', api_key: '',
          timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
          fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '', base_url: '',
          goal: promptText, max_steps: 6, strategy: 'sequential',
          isSelected: true, onDelete: () => deleteNode(masterId),
        }),
        createNode(childResearchId, 'child_agent', 430, 80, {
          label: 'Researcher Agent', master_id: masterId, role: 'Researcher',
          provider: 'openai', model: 'gpt-4o', api_key: '',
          timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
          fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '', base_url: '',
          allowed_tool_ids: [], system_prompt: 'Research the topic and gather high quality facts.',
          isSelected: false, onDelete: () => deleteNode(childResearchId),
        }),
        createNode(childWriterId, 'child_agent', 430, 430, {
          label: 'Writer Agent', master_id: masterId, role: 'Writer',
          provider: 'openai', model: 'gpt-4o', api_key: '',
          timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
          fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '', base_url: '',
          allowed_tool_ids: [], system_prompt: 'Draft a polished response based on the evidence gathered.',
          isSelected: false, onDelete: () => deleteNode(childWriterId),
        }),
        createNode(childReviewerId, 'child_agent', 740, 430, {
          label: 'Reviewer Agent', master_id: masterId, role: 'Reviewer',
          provider: 'openai', model: 'gpt-4o', api_key: '',
          timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
          fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '', base_url: '',
          allowed_tool_ids: [], system_prompt: 'Review the final answer for factuality and clarity.',
          isSelected: false, onDelete: () => deleteNode(childReviewerId),
        }),
        createNode(stopId, 'stop', 860, 280, {
          label: 'Stop', isSelected: false, onDelete: () => deleteNode(stopId),
        }),
      ]

      const nextEdges = [
        { id: edgeId(startId, masterId), source: startId, target: masterId },
        { id: edgeId(masterId, stopId), source: masterId, target: stopId },
        { id: edgeId(masterId, childResearchId), source: masterId, target: childResearchId },
        { id: edgeId(masterId, childWriterId), source: masterId, target: childWriterId },
        { id: edgeId(masterId, childReviewerId), source: masterId, target: childReviewerId },
      ]

      setNodes(nextNodes)
      setEdges(nextEdges)
      setSelectedNodeId(masterId)
      setIsBottomConfigOpen(true)
      return { nodeCount: nextNodes.length, label: 'multi-agent pipeline' }
    }

    if (isRag) {
      const startId = mkId('start')
      const loaderId = mkId('loader')
      const splitterId = mkId('splitter')
      const embId = mkId('embed')
      const vectorId = mkId('vector')
      const retrieverId = mkId('retriever')
      const llmId = mkId('llm')
      const stopId = mkId('stop')

      const nextNodes: FlowNode[] = [
        createNode(startId, 'start', 120, 250, {
          label: 'Start', isSelected: false, onDelete: () => deleteNode(startId),
        }),
        createNode(loaderId, 'doc_loader', 300, 100, {
          label: 'Document Loader', loader_type: 'pdf', source: '', chunk_strategy: 'fixed',
          isSelected: false, onDelete: () => deleteNode(loaderId),
        }),
        createNode(splitterId, 'text_splitter', 520, 100, {
          label: 'Recursive Splitter', splitter_type: 'recursive_character', chunk_size: 512, chunk_overlap: 50,
          isSelected: false, onDelete: () => deleteNode(splitterId),
        }),
        createNode(embId, 'embedding', 740, 100, {
          label: 'Embedding Node', provider: 'local', model: 'sentence-transformers/all-MiniLM-L6-v2', api_key: '',
          isSelected: false, onDelete: () => deleteNode(embId),
        }),
        createNode(vectorId, 'vector_store', 960, 100, {
          label: 'Vector Store', store_type: 'local', collection_name: 'my_documents', connection_string: '', top_k: 5,
          isSelected: false, onDelete: () => deleteNode(vectorId),
        }),
        createNode(retrieverId, 'retriever', 520, 320, {
          label: 'Retriever', search_type: 'similarity', collection_name: 'my_documents', top_k: 4,
          score_threshold: 0, rerank: false,
          embedding_provider: 'local', embedding_model: 'sentence-transformers/all-MiniLM-L6-v2', embedding_api_key: '',
          isSelected: false, onDelete: () => deleteNode(retrieverId),
        }),
        createNode(llmId, 'llm', 760, 320, {
          label: 'RAG Answer Node', provider: 'openai', model: 'gpt-4o',
          temperature: 0.4, max_tokens: 1200, top_p: 1.0,
          api_key: '',
          system_prompt: 'Answer using retrieved context and cite supporting evidence where possible.',
          base_url: '', timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
          fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '',
          isSelected: true, onDelete: () => deleteNode(llmId),
        }),
        createNode(stopId, 'stop', 1000, 320, {
          label: 'Stop', isSelected: false, onDelete: () => deleteNode(stopId),
        }),
      ]

      const nextEdges = [
        { id: edgeId(startId, loaderId), source: startId, target: loaderId },
        { id: edgeId(loaderId, splitterId), source: loaderId, target: splitterId },
        { id: edgeId(splitterId, embId), source: splitterId, target: embId },
        { id: edgeId(embId, vectorId), source: embId, target: vectorId },
        { id: edgeId(vectorId, retrieverId), source: vectorId, target: retrieverId },
        { id: edgeId(retrieverId, llmId), source: retrieverId, target: llmId },
        { id: edgeId(llmId, stopId), source: llmId, target: stopId },
      ]

      setNodes(nextNodes)
      setEdges(nextEdges)
      setSelectedNodeId(llmId)
      setIsBottomConfigOpen(true)
      return { nodeCount: nextNodes.length, label: 'RAG pipeline' }
    }

    const startId = mkId('start')
    const llmId = mkId('llm')
    const stopId = mkId('stop')

    const bestTool = catalog.toolCategories
      .flatMap((c) => c.tools)
      .filter((t) => t.type === 'tool')
      .find((t) => {
        const hay = `${t.id} ${t.name} ${t.description}`.toLowerCase()
        return s.split(/[^a-z0-9]+/).some((token) => token.length > 3 && hay.includes(token))
      })

    const bestMcp = catalog.toolCategories
      .flatMap((c) => c.tools)
      .filter((t) => t.type === 'mcp')
      .find((t) => {
        const hay = `${t.id} ${t.name} ${t.description}`.toLowerCase()
        return s.split(/[^a-z0-9]+/).some((token) => token.length > 3 && hay.includes(token))
      })

    const nextNodes: FlowNode[] = [
      createNode(startId, 'start', 220, 260, {
        label: 'Start', isSelected: false, onDelete: () => deleteNode(startId),
      }),
      createNode(llmId, 'llm', 520, 250, {
        label: 'Prompt Planner', provider: 'openai', model: 'gpt-4o',
        temperature: 0.5, max_tokens: 1024, top_p: 1,
        api_key: '',
        system_prompt: `You are an orchestration assistant. Goal: ${promptText}`,
        base_url: '', timeout_ms: 45000, max_retries: 1, retry_backoff_ms: 500,
        fallback_provider: '', fallback_model: '', fallback_api_key: '', fallback_base_url: '',
        isSelected: true, onDelete: () => deleteNode(llmId),
      }),
      createNode(stopId, 'stop', 840, 260, {
        label: 'Stop', isSelected: false, onDelete: () => deleteNode(stopId),
      }),
    ]

    const nextEdges: { id: string; source: string; target: string }[] = [
      { id: edgeId(startId, llmId), source: startId, target: llmId },
      { id: edgeId(llmId, stopId), source: llmId, target: stopId },
    ]

    if (bestTool) {
      const toolId = mkId('tool')
      nextNodes.push(createNode(toolId, 'tool', 520, 80, {
        label: bestTool.name,
        toolId: bestTool.id,
        toolType: 'tool',
        icon: bestTool.icon,
        description: bestTool.description,
        config: { ...bestTool.default_config },
        isSelected: false,
        onDelete: () => deleteNode(toolId),
      }))
      nextEdges.push({ id: edgeId(llmId, toolId), source: llmId, target: toolId })
    }

    if (bestMcp) {
      const mcpId = mkId('mcp')
      nextNodes.push(createNode(mcpId, 'tool', 760, 80, {
        label: bestMcp.name,
        toolId: bestMcp.id,
        toolType: 'mcp',
        icon: bestMcp.icon,
        description: bestMcp.description,
        config: { ...bestMcp.default_config },
        isSelected: false,
        onDelete: () => deleteNode(mcpId),
      }))
      nextEdges.push({ id: edgeId(llmId, mcpId), source: llmId, target: mcpId })
    }

    setNodes(nextNodes)
    setEdges(nextEdges)
    setSelectedNodeId(llmId)
    setIsBottomConfigOpen(true)
    return { nodeCount: nextNodes.length, label: 'starter pipeline' }
  }, [catalog.toolCategories, deleteNode, setEdges, setNodes, setSelectedNodeId])

  const handleBuildFromPrompt = useCallback(async () => {
    const promptText = buildPrompt.trim()
    if (!promptText || isBuildingFromPrompt) return

    setIsBuildingFromPrompt(true)
    setBuildStatusMsg('')
    try {
      const intent = detectBuildIntent(promptText, buildMode)
      const now = new Date().toISOString()

      // The generator uses the selected (or first) LLM node's provider and key.
      const selectedLlm = nodes.find((n) => n.type === 'llm' && n.data.isSelected) || nodes.find((n) => n.type === 'llm')
      const llmData = (selectedLlm?.data || {}) as Record<string, any>
      const provider = (llmData.provider as string) || 'openai'
      const model = (llmData.model as string) || 'gpt-4o'
      const generatorConfig = {
        provider,
        model,
        api_key: resolveApiKey(provider, (llmData.api_key as string) || ''),
        temperature: Number(llmData.temperature ?? 0.4),
        max_tokens: Number(llmData.max_tokens ?? 1800),
        top_p: Number(llmData.top_p ?? 1),
        base_url: (llmData.base_url as string) || '',
        timeout_ms: 45000,
        max_retries: 1,
        retry_backoff_ms: 400,
        system_prompt: 'You are a robust pipeline architect for Pipesets AI.',
      }

      if (intent === 'tool') {
        setBuildStatusMsg(`Writing tool code with ${provider}/${model}…`)
        let generated: ToolDraft | null = null
        let note = ''
        try {
          const res = await fetch(`${API_BASE}/api/build/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: promptText, mode: 'tool', config: generatorConfig }),
          })
          const payload = await res.json()
          const bp = payload.blueprint ?? {}
          if (res.ok && typeof bp.code === 'string' && bp.code.includes('def run(')) {
            generated = {
              name: bp.name || promptText.slice(0, 40),
              icon: bp.icon || '🔧',
              description: bp.description || promptText,
              code: bp.code,
              config_keys: Array.isArray(bp.config_keys) ? bp.config_keys : [],
              packages: Array.isArray(bp.packages) ? bp.packages : [],
            }
          }
          note = payload.message || ''
        } catch (e: any) {
          note = `Generation request failed: ${e.message}.`
        }

        const baseName = promptText.length > 42 ? `${promptText.slice(0, 39)}...` : promptText
        setToolDraftFromPrompt(generated ?? {
          name: `Tool: ${baseName}`,
          icon: '🔧',
          description: promptText,
          config_keys: ['api_key', 'base_url'],
          code: `def run(input_text: str, config: dict) -> str:\n    # Template only — live generation was unavailable. Replace with your implementation.\n    # Prompt: ${promptText.replace(/'/g, "\\'")}\n    return f"TODO: implement tool logic for: {input_text}"\n`,
        })
        sidebar.setEditingCustomTool(undefined)
        sidebar.setCustomToolModalOpen(true)
        setBuildStatusMsg(generated
          ? `Generated tool code with ${provider}/${model}. Fill in Config Keys, run it on the Test tab, then save.${generated.packages?.length ? ` Install first: ${generated.packages.join(', ')}.` : ''}`
          : `Drafted a template only. ${note}`)
      } else if (intent === 'mcp') {
        const transport: 'stdio' | 'sse' | 'http' = /https?:\/\//i.test(promptText) ? 'sse' : 'stdio'
        const draft: McpDraft = {
          name: 'Prompt MCP Server',
          icon: '🔌',
          description: promptText,
          transport,
          command: 'npx',
          args: ['-y', '@modelcontextprotocol/server-filesystem', '.'],
          env_vars: {},
          url: 'http://localhost:3000/sse',
          headers: {},
        }
        setMcpDraftFromPrompt(draft)
        catalog.setEditingCustomMcp(undefined)
        catalog.setCustomMcpModalOpen(true)
        setBuildStatusMsg('Prepared an MCP server draft. Review transport, command, and credentials in the modal.')
      } else {
        let applied = false
        try {
          const res = await fetch(`${API_BASE}/api/build/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              prompt: promptText,
              mode: 'pipeline',
              config: generatorConfig,
            }),
          })

          const payload: BuildGenerateResponse = await res.json()
          const hydrated = hydrateGeneratedBlueprint(payload.blueprint)
          if (res.ok && payload.success && payload.intent === 'pipeline' && hydrated) {
            setNodes(hydrated.nodes)
            setEdges(hydrated.edges)
            setSelectedNodeId(hydrated.selectedNodeId)
            setIsBottomConfigOpen(true)
            const modeTag = payload.simulated ? 'fallback scaffold' : 'live AI blueprint'
            setBuildStatusMsg(`Generated ${modeTag} with ${payload.provider}/${payload.model}. ${payload.message || 'Review and validate.'}`)
            applied = true
          }
        } catch {
          // Fall through to local scaffold fallback below.
        }

        if (!applied) {
          const result = scaffoldPipelineFromPrompt(promptText)
          setBuildStatusMsg(`Created ${result.label} (${result.nodeCount} nodes) using local scaffold fallback.`)
        }
      }

      setBuildPrompt('')
      console.debug('[prompt-build] created from prompt at', now)
    } finally {
      setIsBuildingFromPrompt(false)
    }
  }, [
    buildMode,
    buildPrompt,
    catalog,
    detectBuildIntent,
    hydrateGeneratedBlueprint,
    isBuildingFromPrompt,
    nodes,
    resolveApiKey,
    scaffoldPipelineFromPrompt,
    setEdges,
    setNodes,
    setSelectedNodeId,
    sidebar,
  ])

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="app-root">
    <TopNav
      view={topView}
      monitorTab={monitorTab}
      automationTab={automationTab}
      onViewChange={setTopView}
      onMonitorTabChange={setMonitorTab}
      onAutomationTabChange={setAutomationTab}
      onOpenSettings={(tab) => { setSettingsTab(tab); setTopView('settings') }}
      tenantId={scope.tenantId}
      tenants={tenants}
      projectId={scope.projectId}
      user={user}
      projects={projects}
      onTenantChange={(tenantId) => {
        setTenantId(tenantId)
        reloadScopedData()
      }}
      onProjectChange={(projectId) => {
        setProjectId(projectId)
        reloadScopedData()
      }}
      onLogout={logout}
    />
    {topView === 'apps' ? (
      <AppsHubView
        apps={savedAppsList}
        currentApp={currentApp}
        onOpenApp={(app) => {
          loadApp(app)
          setTopView('build')
        }}
        onCreateApp={createApp}
        onDeleteApp={deleteApp}
        onRenameApp={promptRenameApp}
        onRefreshApps={() => {
          catalog.bootFetch((apps: AppRecord[]) => {
            setSavedAppsList(apps)
          })
        }}
      />
    ) : topView === 'marketplace' ? (
      <MarketplaceView
        onOpenApp={openAppById}
        onAppsChanged={() => catalog.bootFetch((apps: AppRecord[]) => setSavedAppsList(apps))}
      />
    ) : topView === 'evaluate' ? (
      <div className="operations-view">
        <EvalPanel />
      </div>
    ) : topView === 'monitor' ? (
      <MonitorView tab={monitorTab} apps={savedAppsList} />
    ) : topView === 'automation' ? (
      <AutomationView tab={automationTab} apps={savedAppsList} />
    ) : topView === 'settings' ? (
      <SettingsView
        tab={settingsTab}
        onTabChange={setSettingsTab}
        onPipelineDeleted={(id) => setSavedAppsList((prev) => prev.filter((a) => a.id !== id))}
        onPipelinesCleared={() => setSavedAppsList([])}
        onOpenPipeline={handleOpenPipeline}
        onPackagesChanged={() => { catalog.fetchTools(); refreshAgentCatalog() }}
      />
    ) : topView === 'lab' ? (
      <LabView />
    ) : topView === 'docs' ? (
      <Suspense fallback={<div className="operations-view">Loading docs…</div>}>
        <DocsView page={docPage} onPageChange={setDocPage} />
      </Suspense>
    ) : (
    <main
      className="app-shell"
      style={{
        '--left-panel-width': isLeftCollapsed ? '48px' : `${leftPanelWidth}px`,
        '--right-panel-width': `${rightPanelWidth}px`,
      } as React.CSSProperties}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => e.preventDefault()}
    >

      {/* LEFT SIDEBAR */}
      <Sidebar
        collapsed={isLeftCollapsed}
        onToggleCollapsed={toggleLeftCollapsed}
        providers={catalog.providers}
        toolCategories={catalog.toolCategories}
        toolsError={catalog.toolsError}
        onRetryTools={catalog.fetchTools}
        onManagePackages={() => { setSettingsTab('packages'); setTopView('settings') }}
        onManageAgents={() => { setSettingsTab('agents'); setTopView('settings') }}
        customTools={sidebar.customTools}
        customMcpServers={catalog.customMcpServers}
        connections={catalog.connections}
        knowledgeBases={catalog.knowledgeBases}
        isGeneralSectionOpen={sidebar.isGeneralSectionOpen} setIsGeneralSectionOpen={sidebar.setIsGeneralSectionOpen}
        isLlmSectionOpen={sidebar.isLlmSectionOpen} setIsLlmSectionOpen={sidebar.setIsLlmSectionOpen}
        isToolsSectionOpen={sidebar.isToolsSectionOpen} setIsToolsSectionOpen={sidebar.setIsToolsSectionOpen}
        isMcpSectionOpen={sidebar.isMcpSectionOpen} setIsMcpSectionOpen={sidebar.setIsMcpSectionOpen}
        isToolkitSectionOpen={sidebar.isToolkitSectionOpen} setIsToolkitSectionOpen={sidebar.setIsToolkitSectionOpen}
        isMemorySectionOpen={sidebar.isMemorySectionOpen} setIsMemorySectionOpen={sidebar.setIsMemorySectionOpen}
        isCacheSectionOpen={sidebar.isCacheSectionOpen} setIsCacheSectionOpen={sidebar.setIsCacheSectionOpen}
        isDocLoaderSectionOpen={sidebar.isDocLoaderSectionOpen} setIsDocLoaderSectionOpen={sidebar.setIsDocLoaderSectionOpen}
        isTextSplitterSectionOpen={sidebar.isTextSplitterSectionOpen} setIsTextSplitterSectionOpen={sidebar.setIsTextSplitterSectionOpen}
        isEmbeddingSectionOpen={sidebar.isEmbeddingSectionOpen} setIsEmbeddingSectionOpen={sidebar.setIsEmbeddingSectionOpen}
        isVectorStoreSectionOpen={sidebar.isVectorStoreSectionOpen} setIsVectorStoreSectionOpen={sidebar.setIsVectorStoreSectionOpen}
        isRetrieverSectionOpen={sidebar.isRetrieverSectionOpen} setIsRetrieverSectionOpen={sidebar.setIsRetrieverSectionOpen}
        isAgentsSectionOpen={sidebar.isAgentsSectionOpen} setIsAgentsSectionOpen={sidebar.setIsAgentsSectionOpen}
        isCustomToolsSectionOpen={sidebar.isCustomToolsSectionOpen} setIsCustomToolsSectionOpen={sidebar.setIsCustomToolsSectionOpen}
        isConnectionsSectionOpen={sidebar.isConnectionsSectionOpen} setIsConnectionsSectionOpen={sidebar.setIsConnectionsSectionOpen}
        isKnowledgeBaseSectionOpen={sidebar.isKnowledgeBaseSectionOpen} setIsKnowledgeBaseSectionOpen={sidebar.setIsKnowledgeBaseSectionOpen}
        isPipelinesSectionOpen={sidebar.isPipelinesSectionOpen} setIsPipelinesSectionOpen={sidebar.setIsPipelinesSectionOpen}
        isSkillsSectionOpen={sidebar.isSkillsSectionOpen} setIsSkillsSectionOpen={sidebar.setIsSkillsSectionOpen}
        isFrameworksSectionOpen={sidebar.isFrameworksSectionOpen} setIsFrameworksSectionOpen={sidebar.setIsFrameworksSectionOpen}
        isSyntheticDataSectionOpen={sidebar.isSyntheticDataSectionOpen} setIsSyntheticDataSectionOpen={sidebar.setIsSyntheticDataSectionOpen}
        isRerankerSectionOpen={sidebar.isRerankerSectionOpen} setIsRerankerSectionOpen={sidebar.setIsRerankerSectionOpen}
        isHumanGateSectionOpen={sidebar.isHumanGateSectionOpen} setIsHumanGateSectionOpen={sidebar.setIsHumanGateSectionOpen}
        isCheckpointerSectionOpen={sidebar.isCheckpointerSectionOpen} setIsCheckpointerSectionOpen={sidebar.setIsCheckpointerSectionOpen}
        isWorkflowSectionOpen={sidebar.isWorkflowSectionOpen} setIsWorkflowSectionOpen={sidebar.setIsWorkflowSectionOpen}
        isOutputParserSectionOpen={sidebar.isOutputParserSectionOpen} setIsOutputParserSectionOpen={sidebar.setIsOutputParserSectionOpen}
        isMiddlewareSectionOpen={sidebar.isMiddlewareSectionOpen} setIsMiddlewareSectionOpen={sidebar.setIsMiddlewareSectionOpen}
        collapsedProviders={sidebar.collapsedProviders}
        toggleProviderGroup={toggleProviderGroup}
        searchModelQuery={sidebar.searchModelQuery} setSearchModelQuery={sidebar.setSearchModelQuery}
        searchToolQuery={sidebar.searchToolQuery} setSearchToolQuery={sidebar.setSearchToolQuery}
        searchMcpQuery={sidebar.searchMcpQuery} setSearchMcpQuery={sidebar.setSearchMcpQuery}
        onDragStartLlm={onDragStartLlm}
        onDragStartTool={onDragStartTool}
        onDragStartToolkit={onDragStartToolkit}
        onOpenCustomToolModal={() => { sidebar.setEditingCustomTool(undefined); sidebar.setCustomToolModalOpen(true) }}
        onEditCustomTool={(ct) => { sidebar.setEditingCustomTool(ct); sidebar.setCustomToolModalOpen(true) }}
        onDeleteCustomTool={async (ct) => {
          if (window.confirm(`Delete custom tool "${ct.name}"? This cannot be undone.`)) {
            await fetch(`${API_BASE}/api/custom-tools/${ct.id}`, { method: 'DELETE' })
            fetchCustomTools()
          }
        }}
        onOpenCustomMcpModal={() => { catalog.setEditingCustomMcp(undefined); catalog.setCustomMcpModalOpen(true) }}
        onEditCustomMcp={(s) => { catalog.setEditingCustomMcp(s); catalog.setCustomMcpModalOpen(true) }}
        onDeleteCustomMcp={async (s) => {
          if (window.confirm(`Delete custom MCP server "${s.name}"?`)) {
            await fetch(`${API_BASE}/api/custom-mcp/${s.id}`, { method: 'DELETE' })
            catalog.fetchCustomMcpServers()
          }
        }}
        onOpenConnectionModal={() => { catalog.setEditingConnection(undefined); catalog.setConnectionModalOpen(true) }}
        onEditConnection={(c) => { catalog.setEditingConnection(c); catalog.setConnectionModalOpen(true) }}
        onDeleteConnection={async (c) => {
          if (window.confirm(`Delete connection "${c.name}"?`)) {
            await fetch(`${API_BASE}/api/connections/${c.id}`, { method: 'DELETE' })
            catalog.fetchConnections()
          }
        }}
        onOpenKnowledgeBaseModal={() => { catalog.setEditingKnowledgeBase(undefined); catalog.setKnowledgeBaseModalOpen(true) }}
        onDeleteKnowledgeBase={async (kb) => {
          if (window.confirm(`Delete Knowledge Base "${kb.name}" and all indexed chunks?`)) {
            await fetch(`${API_BASE}/api/knowledge-bases/${kb.id}`, { method: 'DELETE' })
            catalog.fetchKnowledgeBases()
          }
        }}
        skills={catalog.skills}
        onOpenSkillsModal={() => catalog.setSkillsModalOpen(true)}
        onDeleteSkill={async (skill) => {
          if (window.confirm(`Delete skill "${skill.name}"?`)) {
            await fetch(`${API_BASE}/api/skills/${skill.id}`, { method: 'DELETE' })
            catalog.fetchSkills()
          }
        }}
        fetchCustomMcpServers={catalog.fetchCustomMcpServers}
        fetchConnections={catalog.fetchConnections}
        fetchKnowledgeBases={catalog.fetchKnowledgeBases}
        fetchSkills={catalog.fetchSkills}
        fetchCustomTools={fetchCustomTools}
      />

      {/* RESIZE HANDLE */}
      <div
        className="panel-resize-handle"
        onMouseDown={isLeftCollapsed ? undefined : onLeftResizeMouseDown}
        style={isLeftCollapsed ? { pointerEvents: 'none' } : undefined}
        role="separator"
        aria-label="Resize left panel"
      />

      {/* CENTER CANVAS + BOTTOM CONFIG */}
      <section className="center-workspace">
        <div
          className={`canvas-panel${isPublished ? ' canvas-panel--locked' : ''}`}
          onDrop={isPublished ? undefined : onDrop}
          onDragOver={isPublished ? undefined : onDragOver}
        >
          <div className="canvas-header">
            <div className="canvas-title-group">
              <AppSwitcher
                currentApp={currentApp}
                apps={savedAppsList}
                onOpenApp={loadApp}
                onManageApps={() => setIsAppModalOpen(true)}
                onNewApp={() => setIsNewAppModalOpen(true)}
                onRenameApp={promptRenameApp}
              />
              <span className="node-counter">{nodes.length} node{nodes.length === 1 ? '' : 's'}</span>
              {activeNode && (
                <span className="canvas-tag">
                  {activeNode.data.label} <span className="canvas-tag-type">{activeNode.type}</span>
                </span>
              )}
            </div>
            <div className="canvas-actions">
              {/* Version / status badge */}
              {currentApp && (
                <span className={`version-badge ${currentApp.status}`}>
                  {currentApp.status === 'published'
                    ? `v${currentApp.version} · Published`
                    : currentApp.version > 0
                      ? `v${currentApp.version + 1} · Draft`
                      : 'Draft'}
                </span>
              )}

              {appSaveStatus && <span className="save-status-badge">{appSaveStatus}</span>}
              {validationStatusMsg && <span className="validation-status-badge">{validationStatusMsg}</span>}

              {nodes.length > 0 && currentApp?.status !== 'published' && (
                <button type="button" className="clear-btn" onClick={() => { setNodes([]); setSelectedNodeId(null) }}>Clear</button>
              )}
              {currentApp && (
                <button type="button" className="export-trigger-btn" onClick={() => setIsExportModalOpen(true)}>Export</button>
              )}
              {currentApp && (
                <button
                  type="button"
                  className="export-trigger-btn"
                  title="Share this pipeline to the marketplace"
                  onClick={() => setIsMarketplaceModalOpen(true)}
                >
                  Marketplace
                </button>
              )}
              {currentApp && (
                <button
                  type="button"
                  className="export-trigger-btn"
                  title="Get a link anyone can open to chat with this pipeline"
                  onClick={() => setIsChatLinkModalOpen(true)}
                >
                  Chat link
                </button>
              )}

              <span className="canvas-actions-divider" aria-hidden="true" />

              {/* Validate — explicit trigger, status appears only after click */}
              {currentApp?.status !== 'published' && (
                <button type="button" className="validate-pipeline-btn" onClick={runValidation}>Validate</button>
              )}

              {/* Save draft — hidden when pipeline is published (locked) */}
              {currentApp?.status !== 'published' && (
                <button type="button" className="save-app-btn" onClick={saveCurrentApp}>Save draft</button>
              )}

              {/* Publish — only shown while in draft mode */}
              {currentApp?.status !== 'published' && (
                <button type="button" className="publish-btn" onClick={publishApp}>Publish</button>
              )}

              {/* Edit — only shown when published (unlocks for next version) */}
              {currentApp?.status === 'published' && (
                <button type="button" className="edit-pipeline-btn" onClick={startEditing}>Edit pipeline</button>
              )}

            </div>
          </div>

          {currentApp?.status !== 'published' && (
            <div className="prompt-build-bar">
              <div className="prompt-build-controls">
                <textarea
                  className="prompt-build-input"
                  rows={1}
                  placeholder="✨ Describe a tool, MCP server or pipeline to scaffold — e.g. a support pipeline with RAG, a reviewer agent and a Slack tool"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && buildPrompt.trim() && !isBuildingFromPrompt) handleBuildFromPrompt()
                  }}
                  value={buildPrompt}
                  onChange={(e) => setBuildPrompt(e.target.value)}
                />
                <div className="prompt-build-actions">
                  <div className="prompt-build-mode-group" role="group" aria-label="Prompt build mode">
                    {(['auto', 'tool', 'mcp', 'pipeline'] as PromptBuildMode[]).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        className={`prompt-mode-btn ${buildMode === mode ? 'active' : ''}`}
                        onClick={() => setBuildMode(mode)}
                      >
                        {mode === 'auto' ? 'Auto' : mode === 'tool' ? 'Tool' : mode === 'mcp' ? 'MCP' : 'Pipeline'}
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    className="prompt-import-btn"
                    onClick={() => setIsImportCodeModalOpen(true)}
                    title="Convert existing LangChain, CrewAI, AutoGen or plain Python code into a pipeline"
                  >
                    Import code
                  </button>
                  <button
                    type="button"
                    className="prompt-build-generate-btn"
                    disabled={!buildPrompt.trim() || isBuildingFromPrompt}
                    onClick={handleBuildFromPrompt}
                    title="Generate (⌘/Ctrl + Enter)"
                  >
                    {isBuildingFromPrompt ? 'Generating…' : 'Generate'}
                  </button>
                </div>
                {buildStatusMsg && <div className="prompt-build-status">{buildStatusMsg}</div>}
              </div>
            </div>
          )}

          {isImportCodeModalOpen && (
            <ImportCodeModal
              onClose={() => setIsImportCodeModalOpen(false)}
              llmConfig={(() => {
                const llmNode = nodes.find((n) => n.type === 'llm' && (n.data as any).isSelected) || nodes.find((n) => n.type === 'llm')
                const d = (llmNode?.data ?? {}) as Record<string, any>
                return llmNode ? { provider: d.provider, model: d.model, api_key: resolveApiKey(d.provider, d.api_key), base_url: d.base_url } : undefined
              })()}
              onImport={(blueprint, message) => {
                const hydrated = hydrateGeneratedBlueprint(blueprint)
                if (hydrated) {
                  setNodes(hydrated.nodes)
                  setEdges(hydrated.edges)
                  setSelectedNodeId(hydrated.selectedNodeId)
                  setIsBottomConfigOpen(true)
                  setBuildStatusMsg(`↩ ${message}`)
                }
                setIsImportCodeModalOpen(false)
              }}
            />
          )}

          <ReactFlow
            nodes={nodes.map((n) => ({
              ...n,
              className: executingNodeIds.includes(n.id)
                ? `${n.className || ''} executing`.trim()
                : n.className,
            }))}
            edges={edges.map((e) => ({
              ...e,
              type: e.type ?? 'deletable',
              deletable: !isPublished,
              markerEnd: e.markerEnd ?? { type: MarkerType.ArrowClosed },   // edge direction decides step order
              animated: isExecuting && (executingNodeIds.includes(e.source) || executingNodeIds.includes(e.target)),
              className: isExecuting && (executingNodeIds.includes(e.source) || executingNodeIds.includes(e.target))
                ? 'executing'
                : e.className,
            }))}
            onNodesChange={isPublished ? undefined : onNodesChange}
            onEdgesChange={isPublished ? undefined : onEdgesChange}
            onConnect={isPublished ? undefined : onConnect}
            onNodeClick={(e, node) => { onNodeClick(e, node); setIsBottomConfigOpen(true) }}
            onEdgeDoubleClick={isPublished ? undefined : (_, edge) => {
              // Confirm steps branch on edge labels: "yes" / "no"
              const label = window.prompt('Edge label (use "yes" / "no" for Confirm branches; empty to clear):', String(edge.label ?? ''))
              if (label === null) return
              setEdges((es) => es.map((e) => (e.id === edge.id ? { ...e, label: label.trim() || undefined } : e)))
            }}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            deleteKeyCode={isPublished ? null : ['Backspace', 'Delete']}
            nodesDraggable={!isPublished}
            nodesConnectable={!isPublished}
            elementsSelectable={!isPublished}
            connectionRadius={35} fitView fitViewOptions={{ maxZoom: 1, padding: 0.2 }}
            minZoom={0.2} maxZoom={1.75} proOptions={{ hideAttribution: true }} className="flow-surface">
            <FitViewOnOpen key={currentAppId ?? 'none'} />
            <MiniMap pannable zoomable nodeBorderRadius={8} maskColor="rgba(241, 245, 249, 0.7)" />
            <Controls showInteractive={false}>
              {!isPublished && (
                <>
                  <ControlButton onClick={undo} disabled={!canUndo} title="Undo (⌘Z)" aria-label="Undo">
                    <Undo2 />
                  </ControlButton>
                  <ControlButton onClick={redo} disabled={!canRedo} title="Redo (⇧⌘Z)" aria-label="Redo">
                    <Redo2 />
                  </ControlButton>
                </>
              )}
            </Controls>
            <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} color="var(--canvas-dot)" />
          </ReactFlow>
        </div>

        {/* BOTTOM CONFIG PANEL */}
        <div className={`bottom-config-panel ${isBottomConfigOpen ? 'open' : 'collapsed'}`}>
          <div className="bottom-panel-header" onClick={() => setIsBottomConfigOpen(!isBottomConfigOpen)}>
            <div className="bottom-header-title">
              <span className="config-icon">⚙️</span>
              <strong>Configuration Panel</strong>
              {isPublished
                ? activeNode
                  ? <span className="published-lock-badge">🔒 Viewing: <strong>{activeNode.data.label}</strong> — read-only</span>
                  : <span className="published-lock-badge">🔒 Published — select a node to view its config</span>
                : activeNode
                  ? <span className="active-node-badge">Editing: <strong>{activeNode.data.label}</strong> ({activeNode.type === 'middleware' ? 'GUARDRAIL' : activeNode.type?.toUpperCase()})</span>
                  : <span className="hint-text">(Select a node to configure)</span>
              }
            </div>
            <div className="bottom-header-controls">
              <button type="button" className="collapse-toggle-btn"
                onClick={(e) => { e.stopPropagation(); setIsBottomConfigOpen(!isBottomConfigOpen) }}>
                {isBottomConfigOpen ? 'Collapse ▼' : 'Expand ▲'}
              </button>
            </div>
          </div>

          {isBottomConfigOpen && (
            <div className="bottom-panel-body">
              {activeNode && !isPublished && DEBUGGABLE_NODE_TYPES.has(activeNode.type ?? '') && (
                <NodeDebugSection key={`${activeNode.id}:${debugEdit?.nodeId === activeNode.id ? debugEdit.n : 0}`}
                  nodeId={activeNode.id} nodeType={activeNode.type ?? ''}
                  data={activeNode.data as DebugNodeFields} onUpdate={updateNodeData}
                  startEditing={debugEdit?.nodeId === activeNode.id} />
              )}
              {activeNode ? (
                activeNode.type === 'memory' ? (
                  <MemoryConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'cache' ? (
                  <CacheConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'llm' ? (
                  <LlmConfigPanel activeNode={activeNode} providers={catalog.providers} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'toolkit' ? (
                  <ToolkitConfigPanel activeNode={activeNode} toolCategories={catalog.toolCategories} customTools={sidebar.customTools} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'doc_loader' ? (
                  <DocLoaderConfigPanel activeNode={activeNode} nodes={nodes} edges={edges} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'text_splitter' ? (
                  <TextSplitterConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'embedding' ? (
                  <EmbeddingConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'vector_store' ? (
                  <VectorStoreConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'retriever' ? (
                  <RetrieverConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'master_agent' ? (
                  <MasterAgentConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'child_agent' ? (
                  <ChildAgentConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} currentAppId={currentApp?.id} nodes={nodes} edges={edges} />
                ) : activeNode.type === 'connection' ? (
                  <ConnectionConfigPanel activeNode={activeNode as any} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} onHealthChecked={catalog.fetchConnections} readOnly={isPublished} />
                ) : activeNode.type === 'knowledge_base' ? (
                  <KnowledgeBaseConfigPanel activeNode={activeNode as any} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'skill' ? (
                  <SkillConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'start' || activeNode.type === 'stop' ? (
                  <div className="empty-config-state">
                    <span>{activeNode.type === 'start' ? '▶ Start' : '⏹ Stop'} node — no configuration needed.</span>
                  </div>
                ) : activeNode.type === 'gateway' ? (
                  <GatewayConfigPanel activeNode={activeNode as any} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'reranker' ? (
                  <RerankerConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'human_gate' ? (
                  <HumanGateConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'checkpointer' ? (
                  <CheckpointerConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'wf_step' ? (
                  <WorkflowStepConfigPanel activeNode={activeNode} nodes={nodes} edges={edges} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'output_parser' ? (
                  <OutputParserConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished} />
                ) : activeNode.type === 'middleware' ? (
                  <MiddlewareConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished}
                    testLlm={(() => {
                      // The LLM node this guardrail is wired to — judge for Custom Rule tests
                      const linked = edges.filter((e) => e.source === activeNode.id || e.target === activeNode.id)
                        .map((e) => (e.source === activeNode.id ? e.target : e.source))
                      const llm = nodes.find((n) => n.type === 'llm' && linked.includes(n.id))
                      return llm ? (llm.data as import('./types').LlmNodeData) : undefined
                    })()} />
                ) : activeNode.type === 'synthetic_data' ? (
                  <SyntheticDataConfigPanel activeNode={activeNode} onUpdate={updateNodeData} onDelete={deleteNode} onSave={saveCurrentApp} readOnly={isPublished}
                    testLlm={(() => {
                      const linked = edges.filter((e) => e.source === activeNode.id || e.target === activeNode.id)
                        .map((e) => (e.source === activeNode.id ? e.target : e.source))
                      const llm = nodes.find((n) => n.type === 'llm' && linked.includes(n.id)) || nodes.find((n) => n.type === 'llm')
                      const d = llm ? (llm.data as import('./types').LlmNodeData) : undefined
                      if (!d?.provider || !d?.model) return undefined
                      return {
                        provider: d.provider,
                        model: d.model,
                        api_key: resolveApiKey(d.provider, d.api_key),
                        base_url: d.base_url,
                        temperature: d.temperature,
                        max_tokens: d.max_tokens,
                        top_p: d.top_p,
                      }
                    })()} />
                ) : (
                  <ToolConfigPanel
                    activeNode={activeNode}
                    nodes={nodes}
                    edges={edges}
                    onUpdate={updateNodeData}
                    onDelete={deleteNode}
                    onSave={saveCurrentApp}
                    readOnly={isPublished}
                    onEditCustomTool={(rawId) => {
                      const ct = sidebar.customTools.find((t) => t.id === rawId)
                      if (ct) { sidebar.setEditingCustomTool(ct); sidebar.setCustomToolModalOpen(true) }
                    }}
                  />
                )
              ) : (
                <div className="empty-config-state">
                  <span>💡 Select or drag a node to configure it.</span>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* RIGHT RESIZE HANDLE */}
      <div
        className="right-panel-resize-handle"
        onMouseDown={onRightResizeMouseDown}
        role="separator"
        aria-label="Resize right panel"
      />

      {/* RIGHT COLUMN */}
      <RightPanel
        nodes={nodes}
        edges={edges}
        currentAppId={currentApp?.id}
        currentApp={currentApp}
        activeTab={rightPanelTab}
        onTabChange={setRightPanelTab}
        isExpanded={rightPanelWidth >= 500}
        onToggleExpand={() => setRightPanelWidth((w) => (w >= 500 ? 390 : 540))}
        onFocusNode={(nodeId) => {
          setSelectedNodeId(nodeId)
          setIsBottomConfigOpen(true)
        }}
        onUpdateNodeData={updateNodeData}
        onConnectionsChanged={catalog.fetchConnections}
        onOpenMonitor={() => { setMonitorTab('traces'); setTopView('monitor') }}
        onAppUpdated={(updated) => {
          setCurrentApp(updated)
          setSavedAppsList((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
        }}
      />

      {/* CUSTOM TOOL MODAL */}
      {sidebar.customToolModalOpen && (
        <CustomToolModal
          tool={sidebar.editingCustomTool}
          initialDraft={toolDraftFromPrompt ?? undefined}
          onClose={() => {
            sidebar.setCustomToolModalOpen(false)
            sidebar.setEditingCustomTool(undefined)
            setToolDraftFromPrompt(null)
          }}
          onSaved={(saved: CustomToolRecord) => {
            sidebar.setCustomTools((prev) => {
              const idx = prev.findIndex((t) => t.id === saved.id)
              return idx >= 0 ? prev.map((t) => t.id === saved.id ? saved : t) : [saved, ...prev]
            })
            sidebar.setCustomToolModalOpen(false)
            sidebar.setEditingCustomTool(undefined)
            setToolDraftFromPrompt(null)
          }}
        />
      )}

      {/* CUSTOM MCP MODAL */}
      {catalog.customMcpModalOpen && (
        <CustomMcpModal
          server={catalog.editingCustomMcp}
          initialDraft={mcpDraftFromPrompt ?? undefined}
          onClose={() => {
            catalog.setCustomMcpModalOpen(false)
            catalog.setEditingCustomMcp(undefined)
            setMcpDraftFromPrompt(null)
          }}
          onSaved={(saved) => {
            catalog.setCustomMcpServers((prev) => {
              const idx = prev.findIndex((s) => s.id === saved.id)
              return idx >= 0 ? prev.map((s) => s.id === saved.id ? saved : s) : [saved, ...prev]
            })
            catalog.setCustomMcpModalOpen(false)
            catalog.setEditingCustomMcp(undefined)
            setMcpDraftFromPrompt(null)
          }}
        />
      )}

      {/* CONNECTION MODAL */}
      {catalog.connectionModalOpen && (
        <ConnectionModal
          connection={catalog.editingConnection}
          onClose={() => { catalog.setConnectionModalOpen(false); catalog.setEditingConnection(undefined) }}
          onSaved={(saved) => {
            catalog.setConnections((prev) => {
              const idx = prev.findIndex((c) => c.id === saved.id)
              return idx >= 0 ? prev.map((c) => c.id === saved.id ? saved : c) : [saved, ...prev]
            })
            catalog.setConnectionModalOpen(false)
            catalog.setEditingConnection(undefined)
          }}
        />
      )}

      {/* KNOWLEDGE BASE MODAL */}
      {catalog.knowledgeBaseModalOpen && (
        <KnowledgeBaseModal
          kb={catalog.editingKnowledgeBase}
          onClose={() => { catalog.setKnowledgeBaseModalOpen(false); catalog.setEditingKnowledgeBase(undefined) }}
          onSaved={(saved) => {
            catalog.setKnowledgeBases((prev) => {
              const idx = prev.findIndex((k) => k.id === saved.id)
              return idx >= 0 ? prev.map((k) => k.id === saved.id ? saved : k) : [saved, ...prev]
            })
            catalog.setKnowledgeBaseModalOpen(false)
            catalog.setEditingKnowledgeBase(undefined)
          }}
        />
      )}

      {/* SKILLS MODAL */}
      {catalog.skillsModalOpen && (
        <SkillsModal
          skills={catalog.skills}
          isOpen={catalog.skillsModalOpen}
          onClose={() => catalog.setSkillsModalOpen(false)}
          onSave={() => {
            catalog.fetchSkills()
          }}
          onDeleteSkill={async (skill) => {
            if (window.confirm(`Delete skill "${skill.name}"?`)) {
              await fetch(`${API_BASE}/api/skills/${skill.id}`, { method: 'DELETE' })
              catalog.fetchSkills()
            }
          }}
        />
      )}

      {/* EXPORT MODAL */}
      {isMarketplaceModalOpen && currentApp && (
        <PublishListingModal
          app={currentApp}
          onClose={() => setIsMarketplaceModalOpen(false)}
          onPublished={() => {}}
          onPublishApp={publishApp}
        />
      )}
      {isChatLinkModalOpen && currentApp && (
        <ChatLinksModal app={currentApp} onClose={() => setIsChatLinkModalOpen(false)} />
      )}
      {isExportModalOpen && currentApp && (
        <ExportModal appId={currentApp.id} appName={currentApp.name} onClose={() => setIsExportModalOpen(false)} />
      )}

      <PipelinePreviewModal />

      {/* MODAL: Create New App */}
      {isNewAppModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="modal-header">
              <h3>Create New Agentic App</h3>
              {savedAppsList.length > 0 && (
                <button type="button" className="modal-close-btn" onClick={() => setIsNewAppModalOpen(false)}>✕</button>
              )}
            </div>
            <form onSubmit={handleCreateNewApp} className="modal-form">
              <div className="form-group">
                <label className="field-label">Application Name *</label>
                <input type="text" required placeholder="e.g. Customer Support Triage Agent"
                  className="field-input modal-input" value={newAppName}
                  onChange={(e) => setNewAppName(e.target.value)} autoFocus />
              </div>
              <div className="form-group">
                <label className="field-label">Description (Optional)</label>
                <textarea rows={2} placeholder="Brief summary of what this agent does..."
                  className="field-textarea" value={newAppDesc}
                  onChange={(e) => setNewAppDesc(e.target.value)} />
              </div>
              <div className="modal-actions">
                {savedAppsList.length > 0 ? (
                  <button type="button" className="modal-cancel-btn" onClick={() => setIsNewAppModalOpen(false)}>Cancel</button>
                ) : (
                  // First run: starting from someone else's pipeline is a valid alternative
                  <button type="button" className="modal-cancel-btn" onClick={() => { setIsNewAppModalOpen(false); setTopView('marketplace') }}>
                    Browse marketplace instead
                  </button>
                )}
                <button type="submit" className="modal-create-btn" disabled={isCreatingApp}>
                  {isCreatingApp ? 'Creating…' : 'Create Application →'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Switch / Manage Apps */}
      {isAppModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-card wide">
            <div className="modal-header">
              <h3>Saved Applications (SQLite)</h3>
              <button type="button" className="modal-close-btn" onClick={() => setIsAppModalOpen(false)}>✕</button>
            </div>
            <div className="modal-body">
              <div className="modal-apps-list">
                {savedAppsList.map((app) => (
                  <div key={app.id}
                    className={`app-list-item ${currentApp?.id === app.id ? 'active' : ''}`}
                    onClick={() => loadApp(app)}>
                    <div className="app-item-info">
                      <div className="app-item-title-row">
                        <strong>{app.name}</strong>
                        {currentApp?.id === app.id && <span className="active-pill">CURRENT</span>}
                        <span className={`version-badge ${app.status ?? 'draft'}`} style={{ marginLeft: 4 }}>
                          {app.status === 'published'
                            ? `v${app.version} Published`
                            : app.version > 0 ? `v${app.version + 1}-draft` : 'Draft'}
                        </span>
                      </div>
                      <p className="app-item-desc">{app.description || 'No description provided.'}</p>
                      <span className="app-item-meta">
                        Nodes: {app.flow_data?.nodes?.length || 0} • Updated: {new Date(app.updated_at).toLocaleDateString()}
                      </span>
                    </div>
                    <div className="app-item-actions" onClick={(e) => e.stopPropagation()}>
                      <button type="button" className="load-app-btn" onClick={() => loadApp(app)}>Open</button>
                      <button type="button" className="load-app-btn" onClick={() => void promptRenameApp(app)}>Rename</button>
                      <button type="button" className="delete-app-btn" onClick={() => deleteApp(app.id)}>Delete</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="modal-actions">
              <button type="button" className="modal-create-btn"
                onClick={() => { setIsAppModalOpen(false); setIsNewAppModalOpen(true) }}>
                + Create New App
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
    )}
    </div>
  )
}

export default function App() {
  return (
    <CredentialsProvider>
      <ReactFlowProvider>
        <FlowBuilder />
      </ReactFlowProvider>
    </CredentialsProvider>
  )
}
