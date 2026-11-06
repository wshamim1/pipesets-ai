import type { FlowEdge, FlowNode } from '../types'
import { DB_LOADER_TYPES, getDocLoader } from './docLoaders'
import { requiredConfigFor } from './toolCatalog'
import { describeSkillIssue, skillReadiness } from './skillReadiness'

export type ValidationSeverity = 'error' | 'warn'

export interface ValidationIssue {
  id: string
  severity: ValidationSeverity
  title: string
  hint: string
  nodeId?: string
}

function providerNeedsKey(provider: string): boolean {
  const p = provider.toLowerCase()
  return !(p === 'mock' || p === 'local' || p === 'ollama' || p === 'llamacpp' || p === 'jan')
}

function nodeLabel(node: FlowNode): string {
  const data = node.data as Record<string, any>
  return String(data.label ?? node.type)
}

export function validatePipeline(
  nodes: FlowNode[],
  edges: FlowEdge[],
  resolveApiKey: (provider: string, nodeKey?: string) => string,
  /** Required config keys per tool id (from the catalog, see useRequiredConfig). */
  requiredConfig: (toolId: string) => string[] = requiredConfigFor,
): ValidationIssue[] {
  const issues: ValidationIssue[] = []

  // A pipeline child is runnable on its own: the called pipeline brings its own LLM
  const hasRunnable = nodes.some((n) => n.type === 'llm' || n.type === 'master_agent' || n.type === 'wf_step'
    || (n.type === 'child_agent' && (n.data as Record<string, any>).kind === 'pipeline'))
  if (!hasRunnable) {
    issues.push({
      id: 'missing-runnable-node',
      severity: 'error',
      title: 'No runnable node',
      hint: 'Add an LLM node, a Master Agent node, a Pipeline node or Workflow Steps before running prompts.',
    })
  }

  const starts = nodes.filter((n) => n.type === 'start')
  const stops = nodes.filter((n) => n.type === 'stop')
  if (starts.length === 0) {
    issues.push({
      id: 'missing-start-node',
      severity: 'warn',
      title: 'Missing Start node',
      hint: 'Add a Start node for clearer pipeline entry behavior.',
    })
  }
  if (stops.length === 0) {
    issues.push({
      id: 'missing-stop-node',
      severity: 'warn',
      title: 'Missing Stop node',
      hint: 'Add a Stop node to define the pipeline exit.',
    })
  }

  const nodeDegree = new Map<string, number>()
  for (const n of nodes) nodeDegree.set(n.id, 0)
  for (const e of edges) {
    nodeDegree.set(e.source, (nodeDegree.get(e.source) ?? 0) + 1)
    nodeDegree.set(e.target, (nodeDegree.get(e.target) ?? 0) + 1)
  }

  for (const n of starts) {
    const hasOutgoing = edges.some((e) => e.source === n.id)
    if (!hasOutgoing) {
      issues.push({
        id: `start-unwired-${n.id}`,
        severity: 'warn',
        title: 'Start node is not wired',
        hint: `Connect "${nodeLabel(n)}" to the first processing node.`,
        nodeId: n.id,
      })
    }
  }

  for (const n of stops) {
    const hasIncoming = edges.some((e) => e.target === n.id)
    if (!hasIncoming) {
      issues.push({
        id: `stop-unwired-${n.id}`,
        severity: 'warn',
        title: 'Stop node is not wired',
        hint: `Connect a node output into "${nodeLabel(n)}".`,
        nodeId: n.id,
      })
    }
  }

  const criticalNodes = nodes.filter((n) => (
    n.type === 'llm' ||
    n.type === 'master_agent' ||
    n.type === 'doc_loader' ||
    n.type === 'vector_store' ||
    n.type === 'retriever' ||
    n.type === 'child_agent'
  ))

  for (const n of criticalNodes) {
    if ((nodeDegree.get(n.id) ?? 0) === 0) {
      issues.push({
        id: `isolated-${n.id}`,
        severity: 'warn',
        title: `${nodeLabel(n)} is isolated`,
        hint: 'Connect this node to the pipeline flow so it can participate in execution.',
        nodeId: n.id,
      })
    }
  }

  const llmLikeNodes = nodes.filter((n) => (
    n.type === 'llm' ||
    n.type === 'master_agent' ||
    n.type === 'child_agent' ||
    n.type === 'embedding' ||
    n.type === 'retriever'
  ))

  for (const node of llmLikeNodes) {
    const data = node.data as Record<string, any>
    let provider = ''
    let nodeKey = ''

    if (node.type === 'child_agent' && data.kind === 'pipeline') {
      if (!String(data.app_id ?? '').trim()) {
        issues.push({
          id: `pipeline-child-unset-${node.id}`,
          severity: 'error',
          title: 'Pipeline agent has no pipeline selected',
          hint: `Pick a published pipeline for "${nodeLabel(node)}".`,
          nodeId: node.id,
        })
      }
      continue
    }

    if (node.type === 'child_agent' && data.kind === 'external') {
      const url = String(data.endpoint_url ?? '').trim()
      if (!/^https?:\/\/\S+$/i.test(url)) {
        issues.push({
          id: `external-endpoint-${node.id}`,
          severity: 'error',
          title: 'External agent endpoint is invalid',
          hint: `Set an http(s) endpoint URL for "${nodeLabel(node)}".`,
          nodeId: node.id,
        })
      }
      const authType = String(data.auth_type ?? 'bearer')
      if (authType !== 'none' && !String(data.api_key ?? '').trim()) {
        issues.push({
          id: `external-auth-${node.id}`,
          severity: 'warn',
          title: 'External agent has no credential',
          hint: `Add a token/API key for "${nodeLabel(node)}" or set Auth to None.`,
          nodeId: node.id,
        })
      }
      continue
    }

    if (node.type === 'retriever') {
      provider = String(data.embedding_provider ?? '')
      nodeKey = String(data.embedding_api_key ?? '')
    } else {
      provider = String(data.provider ?? '')
      nodeKey = String(data.api_key ?? '')
    }

    if (!provider) continue
    // Local providers need no key, but their timeout / retry / fallback settings still get checked
    if (providerNeedsKey(provider) && !resolveApiKey(provider, nodeKey)) {
      issues.push({
        id: `missing-key-${node.id}`,
        severity: 'error',
        title: `Missing ${provider} API key`,
        hint: `Set an API key for "${nodeLabel(node)}" in node config or global API Keys.`,
        nodeId: node.id,
      })
    }

    if (node.type === 'llm') {
      const timeoutMs = Number(data.timeout_ms ?? 45000)
      const maxRetries = Number(data.max_retries ?? 1)
      const backoffMs = Number(data.retry_backoff_ms ?? 500)

      if (!Number.isFinite(timeoutMs) || timeoutMs < 1000) {
        issues.push({
          id: `invalid-timeout-${node.id}`,
          severity: 'warn',
          title: 'Timeout is too low',
          hint: `Set timeout >= 1000 ms on "${nodeLabel(node)}" for stable execution.`,
          nodeId: node.id,
        })
      }

      if (!Number.isFinite(maxRetries) || maxRetries < 0 || maxRetries > 5) {
        issues.push({
          id: `invalid-retries-${node.id}`,
          severity: 'warn',
          title: 'Retry count is out of range',
          hint: `Set max retries between 0 and 5 on "${nodeLabel(node)}".`,
          nodeId: node.id,
        })
      }

      if (!Number.isFinite(backoffMs) || backoffMs < 0) {
        issues.push({
          id: `invalid-backoff-${node.id}`,
          severity: 'warn',
          title: 'Retry backoff is invalid',
          hint: `Set retry backoff >= 0 ms on "${nodeLabel(node)}".`,
          nodeId: node.id,
        })
      }

      const fallbackProvider = String(data.fallback_provider ?? '').trim()
      const fallbackModel = String(data.fallback_model ?? '').trim()
      const fallbackNodeKey = String(data.fallback_api_key ?? '')

      if (fallbackProvider === 'mock') {
        issues.push({
          id: `fallback-mock-unsupported-${node.id}`,
          severity: 'warn',
          title: 'Mock fallback is simulation-only',
          hint: `Use a real fallback provider on "${nodeLabel(node)}" for live failover behavior.`,
          nodeId: node.id,
        })
      }

      if (fallbackProvider && !fallbackModel) {
        issues.push({
          id: `fallback-model-missing-${node.id}`,
          severity: 'warn',
          title: 'Fallback model is missing',
          hint: `Set a fallback model for "${nodeLabel(node)}" or clear fallback provider.`,
          nodeId: node.id,
        })
      }

      if (fallbackProvider && fallbackModel && providerNeedsKey(fallbackProvider)) {
        const fallbackResolved = resolveApiKey(fallbackProvider, fallbackNodeKey)
        if (!fallbackResolved) {
          issues.push({
            id: `fallback-key-missing-${node.id}`,
            severity: 'warn',
            title: `Fallback ${fallbackProvider} API key is missing`,
            hint: `Set fallback API key for "${nodeLabel(node)}" or add a global key for ${fallbackProvider}.`,
            nodeId: node.id,
          })
        }
      }
    }
  }

  // A tool missing a required credential/setting would run and fail (or the LLM would answer without it)
  for (const tool of nodes.filter((n) => n.type === 'tool')) {
    const toolData = tool.data as Record<string, any>
    const missing = requiredConfig(toolData.toolId)
      .filter((key) => !String(toolData.config?.[key] ?? '').trim())
    if (missing.length === 0) continue
    issues.push({
      id: `tool-config-missing-${tool.id}`,
      severity: 'error',
      title: `${nodeLabel(tool)} needs ${missing.join(', ')}`,
      hint: 'Pick a saved secret (or fill in the value) in the tool\'s Parameters & Auth.',
      nodeId: tool.id,
    })
  }

  // A wired Connection node that failed its health check breaks every tool/loader using it
  for (const conn of nodes.filter((n) => n.type === 'connection')) {
    const connData = conn.data as Record<string, any>
    if (connData.status !== 'error' || (nodeDegree.get(conn.id) ?? 0) === 0) continue
    issues.push({
      id: `connection-error-${conn.id}`,
      severity: 'error',
      title: `${nodeLabel(conn)} can't connect`,
      hint: String(connData.status_msg || 'Check the host, port and credentials, then re-test the connection.'),
      nodeId: conn.id,
    })
  }

  for (const loader of nodes.filter((n) => n.type === 'doc_loader')) {
    const loaderData = loader.data as Record<string, any>
    const loaderDef = getDocLoader(loaderData?.loader_type)
    if (loaderDef && loaderDef.available === false) {
      issues.push({
        id: `loader-unavailable-${loader.id}`,
        severity: 'error',
        title: `${loaderDef.label} loader isn't available yet`,
        hint: `Swap "${nodeLabel(loader)}" for an available loader (e.g. Web URL, PDF, Directory) in its config.`,
        nodeId: loader.id,
      })
      continue
    }
    if (DB_LOADER_TYPES.has(loaderData?.loader_type)) {
      const hasConnection = edges.some((e) => {
        if (e.source !== loader.id && e.target !== loader.id) return false
        const otherId = e.source === loader.id ? e.target : e.source
        return nodes.some((n) => n.id === otherId && n.type === 'connection')
      })
      if (!hasConnection) {
        issues.push({
          id: `loader-connection-${loader.id}`,
          severity: 'error',
          title: 'Database loader has no Connection node',
          hint: `Drag a Connection node onto the canvas and link it to "${nodeLabel(loader)}".`,
          nodeId: loader.id,
        })
      }
      continue
    }
    const source = String(loaderData?.source ?? '').trim()
    if (!source) {
      issues.push({
        id: `loader-source-${loader.id}`,
        severity: 'error',
        title: 'Document loader source is empty',
        hint: `Set source path/URL for "${nodeLabel(loader)}".`,
        nodeId: loader.id,
      })
    }
  }

  for (const store of nodes.filter((n) => n.type === 'vector_store')) {
    const collection = String((store.data as Record<string, any>)?.collection_name ?? '').trim()
    if (!collection) {
      issues.push({
        id: `vector-collection-${store.id}`,
        severity: 'error',
        title: 'Vector store collection is empty',
        hint: `Set collection_name for "${nodeLabel(store)}".`,
        nodeId: store.id,
      })
    }
  }

  // Skills whose tools aren't attached or set up (the server refuses to publish these too)
  for (const issue of skillReadiness(nodes, edges, requiredConfig)) {
    issues.push({
      id: `skill-not-ready-${issue.skillNodeId}-${issue.llmNodeId}`,
      severity: 'error',
      title: `Skill “${issue.skill}” isn't ready`,
      hint: `${describeSkillIssue(issue)[0].toUpperCase()}${describeSkillIssue(issue).slice(1)} — its tools must be on the LLM node it's wired to.`,
      nodeId: issue.skillNodeId,
    })
  }

  for (const retriever of nodes.filter((n) => n.type === 'retriever')) {
    const collection = String((retriever.data as Record<string, any>)?.collection_name ?? '').trim()
    if (!collection) {
      issues.push({
        id: `retriever-collection-${retriever.id}`,
        severity: 'error',
        title: 'Retriever collection is empty',
        hint: `Set collection_name for "${nodeLabel(retriever)}" so retrieval can run.`,
        nodeId: retriever.id,
      })
    }
  }

  return issues
}
