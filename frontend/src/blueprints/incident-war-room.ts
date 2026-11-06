import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, child, tool, start, stop } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-incident-war-room',
  name: 'Incident War Room',
  description: 'A master agent runs Alert Triage, Log Investigator and an endpoint checker in parallel, then drafts an incident update that a human reviews and edits.',
  badge: 'DevOps',
  icon: '🚨',
  order: 170,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'master-1', type: 'master_agent', position: { x: 300, y: 250 }, data: {
        label: 'Incident Commander', provider: 'openai', model: 'gpt-4o', api_key: '',
        goal: 'Work out what is broken, since when and why, and draft a short incident update: impact, cause with evidence, next steps.',
        max_steps: 5, strategy: 'parallel',
      }},
      { id: 'child-alerts', type: 'child_agent', position: { x: 600, y: 60 }, data: child(
        'Alert Triage', 'Alert Triage',
        'List what is firing in Alertmanager, group alerts that share a cause and rank them by impact. Never silence or acknowledge anything.',
      )},
      { id: 'child-logs', type: 'child_agent', position: { x: 600, y: 250 }, data: child(
        'Log Investigator', 'Log Investigator',
        'Search the logs (LogQL) for the errors behind the incident: when they started, how often, where. Quote 2–3 lines with timestamps and the queries you ran.',
      )},
      { id: 'child-edge', type: 'child_agent', position: { x: 600, y: 440 }, data: child(
        'Endpoint Checker', 'Incident Responder',
        'Check the affected URLs (status, latency, TLS) and whether a SaaS dependency (GitHub, Cloudflare, OpenAI…) reports an outage.',
      )},
      tool('tool-am', 900, 60, 'Alertmanager', 'alertmanager', '🚨', 'Reads active alerts and silences (read-only).',
        { base_url: '', token: '', action: 'alerts', include_silenced: false }),
      tool('tool-loki', 900, 250, 'Loki', 'loki_query', '🪵', 'Runs LogQL queries against Loki or Grafana Cloud Logs.',
        { base_url: '', token: '', username: '', org_id: '', lookback: '1h', max_results: 50 }),
      tool('tool-health', 900, 400, 'Website Health Check', 'website_health_check', '🩺',
        'Checks URLs: status code, response time, redirects and TLS.', { timeout: 10, expected_status: 200, cert_warning_days: 21 }),
      tool('tool-status', 900, 520, 'Service Status', 'service_status', '🟢', 'Checks SaaS providers\' public status pages.', {}),
      { id: 'gate-1', type: 'human_gate', position: { x: 300, y: 470 }, data: {
        label: 'Approve Update', gate_type: 'edit',
        prompt_message: 'Check and edit the incident update before it goes out.', timeout_hours: 2, on_timeout: 'reject',
      }},
      stop(300, 640),
    ]
    const edges: FlowEdge[] = [
      edge('e-start-master', 'start-1', 'master-1'),
      edge('e-master-alerts', 'master-1', 'child-alerts'),
      edge('e-master-logs', 'master-1', 'child-logs'),
      edge('e-master-edge', 'master-1', 'child-edge'),
      edge('e-alerts-am', 'child-alerts', 'tool-am'),
      edge('e-logs-loki', 'child-logs', 'tool-loki'),
      edge('e-edge-health', 'child-edge', 'tool-health'),
      edge('e-edge-status', 'child-edge', 'tool-status'),
      edge('e-master-gate', 'master-1', 'gate-1'),
      edge('e-gate-stop', 'gate-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
