import type { AppRecord } from '../../types'

export type Requirement = {
  kind: 'provider_key' | 'connection' | 'data_source' | 'child_pipeline' | 'secret' | 'tool_config'
  label: string
  detail: string
  provider?: string
  node_id?: string
}

export type Listing = {
  id: string
  name: string
  summary: string
  description: string
  category: string
  tags: string[]
  visibility: 'public' | 'tenant'
  status: 'listed' | 'unlisted'
  latest_version: number
  import_count: number
  try_count: number
  publisher: { tenant_id: string; tenant_name: string; user_name: string }
  is_mine: boolean
  source_app_id: string | null
  created_at: string
  updated_at: string
  node_count: number
  node_types: Record<string, number>
  uses_agents: boolean
  uses_rag: boolean
  requirements: Requirement[]
  bundled_tool_names: string[]
  can_try: boolean
  try_blocked_reason: string
}

export type ListingDetail = Listing & {
  version: number
  versions: Array<{ version: number; changelog: string; created_at: string; source_app_version: number }>
  flow_data: AppRecord['flow_data']
  bundled_tools: Array<{ ref: string; name: string; icon: string; description: string; code: string; config_keys: string[] }>
  docs: string
}

export const CATEGORY_LABELS: Record<string, string> = {
  general: 'General',
  rag: 'RAG & Knowledge',
  agents: 'Multi-Agent',
  customer_support: 'Customer Support',
  data: 'Data & SQL',
  content: 'Content',
  dev_tools: 'Developer Tools',
  research: 'Research',
}

export const REQUIREMENT_ICONS: Record<Requirement['kind'], string> = {
  provider_key: '🔑',
  connection: '🔌',
  data_source: '📚',
  child_pipeline: '🔗',
  secret: '🔒',
  tool_config: '⚙️',
}

export async function errorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const payload = await res.json()
    return typeof payload?.detail === 'string' ? payload.detail : fallback
  } catch {
    return fallback
  }
}
