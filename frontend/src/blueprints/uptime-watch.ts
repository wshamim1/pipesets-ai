import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-uptime-watch',
  name: 'Uptime & Certificate Watch',
  description: 'Checks your sites\' status, response time, TLS expiry, DNS and mail records, plus your SaaS providers\' status pages. No API keys needed.',
  badge: 'DevOps',
  icon: '🔐',
  order: 300,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Site Checker',
        'You check websites and domains the user lists. For each URL: status, response time and redirects. For each host: the TLS '
        + 'certificate and days to expiry (warn under 30, alert under 7). For each domain: DNS records including SPF and DMARC. Also '
        + 'check the status pages of any SaaS providers named. Report a table per site with ✅ / ⚠️ / ❌ and what to fix first. '
        + 'Only check what is asked — no port or path scanning.',
        0.2,
      )},
      tool('tool-health', 340, 520, 'Website Health Check', 'website_health_check', '🩺', 'Status, response time, redirects.',
        { timeout: 10, expected_status: 200, cert_warning_days: 21 }),
      tool('tool-tls', 600, 520, 'TLS Certificate Check', 'ssl_certificate_check', '🔐', 'Certificate validity, issuer and expiry.',
        { warn_days: 30, timeout: 10 }),
      tool('tool-dns', 860, 520, 'DNS & WHOIS', 'dns_whois', '🧭', 'DNS records and domain registration.',
        { mode: 'both', record_types: 'A,AAAA,MX,TXT,NS,CNAME' }),
      tool('tool-status', 1120, 520, 'Service Status', 'service_status', '🟢', 'SaaS providers\' public status pages.', {}),
      stop(700),
    ]
    const edges = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-health', 'llm-1', 'tool-health'),
      edge('e-llm-tls', 'llm-1', 'tool-tls'),
      edge('e-llm-dns', 'llm-1', 'tool-dns'),
      edge('e-llm-status', 'llm-1', 'tool-status'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
