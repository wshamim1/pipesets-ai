import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, tool, start, stop } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-k8s-doctor',
  name: 'Kubernetes Crash Doctor',
  description: 'Reads pods, warning events and crashed containers\' logs (read-only) and explains why a workload is crash-looping or pending.',
  badge: 'DevOps',
  icon: '☸️',
  order: 200,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Kubernetes Troubleshooter',
        'You troubleshoot Kubernetes workloads, read-only. List the pods, find the ones not ready, restarting or pending and their '
        + 'reason; read their warning events; for crashing containers read the previous instance\'s logs and quote the error; '
        + 'check the deployment\'s ready replicas. Answer with the failing workload, the root cause with evidence, and the fix '
        + '(give kubectl commands as suggestions only). Never delete, restart, scale or patch anything.',
        0.2,
      )},
      tool('tool-k8s', 340, 520, 'Kubernetes', 'kubernetes', '☸️', 'Reads pods, events, logs and deployments (read-only).',
        { api_url: '', token: '', namespace: 'default', action: 'pods', container: '', previous: false, verify_tls: true }),
      stop(700),
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-k8s', 'llm-1', 'tool-k8s'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
