import type { ReactNode } from 'react'
import { useTenantContext } from '../../context/TenantContext'
import { IamAdminPanel } from '../ops/IamAdminPanel'
import { ApiKeysPanel } from '../ops/ApiKeysPanel'
import { AuditLogPanel } from '../ops/AuditLogPanel'
import { GlobalAdminPanel } from '../ops/GlobalAdminPanel'
import { AdminConsolePanel } from './AdminConsolePanel'
import { DatabasePanel } from './DatabasePanel'
import { ModelBackendsPanel } from './ModelBackendsPanel'
import { ProviderKeysPanel } from './ProviderKeysPanel'
import { SecretsPanel } from './SecretsPanel'
import { ShareTunnelPanel } from './ShareTunnelPanel'
import { ToolPackagesPanel } from './ToolPackagesPanel'
import { AgentPackagesPanel } from './AgentPackagesPanel'
import type { SettingsTab } from '../TopNav'

interface Props {
  tab: SettingsTab
  onTabChange: (tab: SettingsTab) => void
  onPipelineDeleted: (id: string) => void
  onPipelinesCleared: () => void
  onOpenPipeline: (id: string) => void
  /** A package was installed or uninstalled: reload the tool catalog the sidebar shows. */
  onPackagesChanged?: () => void
}

// serverOnly: shown to server admins only (the page itself also refuses everyone else)
const SECTIONS: { heading: string; items: { id: SettingsTab; label: string; title: string; description: string; serverOnly?: boolean }[] }[] = [
  {
    heading: 'Workspace',
    items: [
      { id: 'members', label: 'Members & access', title: 'Members & access', description: 'Users, groups and the access rules (ACLs) that decide who can read, edit or run what.' },
      { id: 'workspaces', label: 'Workspaces & projects', title: 'Workspaces & projects', description: 'Workspaces (tenants) and the projects inside them that scope apps, runs and keys.' },
      { id: 'apikeys', label: 'API keys', title: 'API keys', description: 'Keys that let external apps, scripts and MCP clients call your published pipelines through /v1.' },
      { id: 'audit', label: 'Audit log', title: 'Audit log', description: 'Who changed keys, secrets, access, workspaces and publishing — and who was refused. Filter, page back, or export as CSV or JSON Lines.' },
    ],
  },
  {
    heading: 'Builder',
    items: [
      { id: 'packages', label: 'Tools & MCP packages', title: 'Tools & MCP packages', description: 'Install the built-in tools and MCP servers this workspace uses. Installed ones appear as nodes in the builder; the rest stay here until you need them.' },
      { id: 'agents', label: 'Agents', title: 'Agents', description: 'Install the built-in agents this workspace uses, and the tools they need. Installed ones appear under Agents in the builder; your own saved agents are always there.' },
    ],
  },
  {
    heading: 'Keys & secrets',
    items: [
      { id: 'providerkeys', label: 'Model provider keys', title: 'Model provider keys', description: 'The default OpenAI, Anthropic and other model keys for this project, used by any model node without its own key.' },
      { id: 'backends', label: 'Model backends', title: 'Model backends', description: 'Which engine sends each provider\'s model calls — the built-in adapter or the optional LiteLLM fallback — and the server address it uses, for this project or the whole workspace.' },
      { id: 'secrets', label: 'Secrets', title: 'Secrets', description: 'Encrypted API keys, tokens and webhook URLs that tools and nodes reference — LLM keys and tool keys are kept apart.' },
    ],
  },
  {
    heading: 'Server',
    items: [
      { id: 'admin', label: 'Admin console', title: 'Admin console', description: 'Every user, workspace and pipeline on this server: disable accounts, reset passwords, grant admin, and review what each workspace is running. Other workspaces\' pipelines are view-only until you join them, and every action is audited.', serverOnly: true },
      { id: 'database', label: 'Database', title: 'Database', description: 'Which database this server stores everything in, whether its schema is current, and how to move to another one.', serverOnly: true },
      { id: 'tunnel', label: 'Share via ngrok', title: 'Share via ngrok', description: 'Open this development server to the internet for a while, to try the UI on a phone or show it to someone.', serverOnly: true },
    ],
  },
  {
    heading: 'System',
    items: [
      { id: 'system', label: 'Status & data', title: 'Status & data', description: 'Backend health, integrations and usage per pipeline.' },
      { id: 'danger', label: 'Danger zone', title: 'Danger zone', description: 'Bulk actions that cannot be undone.' },
    ],
  },
]

// Card catalogues use the full width; forms stay at a readable measure
const WIDE_TABS = new Set(['packages', 'agents', 'admin'])

export function SettingsView({ tab, onTabChange, onPipelineDeleted, onPipelinesCleared, onOpenPipeline, onPackagesChanged }: Props) {
  const { serverAdmin } = useTenantContext()
  const sections = SECTIONS.map((s) => ({ ...s, items: s.items.filter((i) => !i.serverOnly || serverAdmin) }))
    .filter((s) => s.items.length > 0)
  const current = SECTIONS.flatMap((s) => s.items).find((i) => i.id === tab) ?? SECTIONS[0].items[0]

  let body: ReactNode
  switch (tab) {
    case 'members':      body = <IamAdminPanel section="members" />; break
    case 'workspaces':   body = <IamAdminPanel section="workspaces" />; break
    case 'apikeys':      body = <ApiKeysPanel />; break
    case 'audit':        body = <AuditLogPanel />; break
    case 'providerkeys': body = <ProviderKeysPanel />; break
    case 'backends':     body = <ModelBackendsPanel />; break
    case 'secrets':      body = <SecretsPanel />; break
    case 'packages':     body = <ToolPackagesPanel onChanged={onPackagesChanged} />; break
    case 'agents':       body = <AgentPackagesPanel onToolsChanged={onPackagesChanged} />; break
    case 'admin':        body = <AdminConsolePanel />; break
    case 'database':     body = <DatabasePanel />; break
    case 'tunnel':       body = <ShareTunnelPanel />; break
    case 'system':
    case 'danger':
      body = (
        <GlobalAdminPanel
          section={tab}
          onPipelineDeleted={onPipelineDeleted}
          onPipelinesCleared={onPipelinesCleared}
          onOpenPipeline={onOpenPipeline}
        />
      )
      break
  }

  return (
    <div className="settings-view">
      <nav className="settings-nav" aria-label="Settings">
        <h1 className="settings-nav-title">Settings</h1>
        {sections.map((section) => (
          <div key={section.heading} className="settings-nav-section">
            <div className="settings-nav-heading">{section.heading}</div>
            {section.items.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`settings-nav-item${tab === item.id ? ' settings-nav-item--active' : ''}${item.id === 'danger' ? ' settings-nav-item--danger' : ''}`}
                aria-current={tab === item.id ? 'page' : undefined}
                onClick={() => onTabChange(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        ))}
      </nav>

      <main className={`settings-content${WIDE_TABS.has(tab) ? ' settings-content--wide' : ''}`}>
        <header className="settings-content-header">
          <h2>{current.title}</h2>
          <p>{current.description}</p>
        </header>
        {body}
      </main>
    </div>
  )
}
