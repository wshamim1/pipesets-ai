import type { FlowNode, FlowEdge } from '../types'
import { PromptRunner } from './PromptRunner'
import { ActiveAppOverviewPanel } from './ActiveAppOverviewPanel'
import { PipelineDocsPanel } from './PipelineDocsPanel'
import { SchedulesPanel } from './SchedulesPanel'
import { WebhooksPanel } from './WebhooksPanel'
import type { AppRecord } from '../types'
import type { RightPanelTab as Tab } from '../utils/appUrl'

const TABS: { id: Tab; label: string }[] = [
  { id: 'run',      label: 'Run' },
  { id: 'overview', label: 'Details' },
  { id: 'docs',     label: 'Docs' },
  { id: 'schedules', label: 'Schedules' },
  { id: 'webhooks', label: 'Webhooks' },
]

interface Props {
  nodes: FlowNode[]
  edges: FlowEdge[]
  currentAppId?: string
  currentApp: AppRecord | null
  activeTab: Tab
  onTabChange: (tab: Tab) => void
  isExpanded: boolean
  onToggleExpand: () => void
  onFocusNode?: (nodeId: string) => void
  onUpdateNodeData?: (nodeId: string, fields: Record<string, any>) => void
  onConnectionsChanged?: () => void
  onOpenMonitor?: () => void
  onAppUpdated: (app: AppRecord) => void
}

export function RightPanel({
  nodes,
  edges,
  currentAppId,
  currentApp,
  activeTab,
  onTabChange,
  isExpanded,
  onToggleExpand,
  onFocusNode,
  onUpdateNodeData,
  onConnectionsChanged,
  onOpenMonitor,
  onAppUpdated,
}: Props) {
  return (
    <div className="right-panel">
      {/* Tab bar */}
      <div className="right-panel-tabs">
        <div className="right-panel-tabs-scroll">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              className={`right-tab-btn${activeTab === id ? ' right-tab-btn--active' : ''}`}
              onClick={() => onTabChange(id)}
            >
              <span className="right-tab-label">{label}</span>
            </button>
          ))}
        </div>
        <div className="right-panel-tabs-actions">
          <button
            type="button"
            className="right-tab-expand-btn"
            onClick={onToggleExpand}
            title={isExpanded ? 'Collapse right panel' : 'Expand right panel'}
            aria-label={isExpanded ? 'Collapse right panel' : 'Expand right panel'}
          >
            {isExpanded ? '⇥' : '⇤'}
          </button>
        </div>
      </div>

      {/* Tab body */}
      <div className="right-panel-body">
        {activeTab === 'overview' && (
          <ActiveAppOverviewPanel
            currentApp={currentApp}
            nodes={nodes}
            edges={edges}
            onFocusNode={onFocusNode}
            onOpenMonitor={onOpenMonitor}
          />
        )}
        {activeTab === 'docs' && (
          <PipelineDocsPanel currentApp={currentApp} nodes={nodes} edges={edges} onAppUpdated={onAppUpdated} />
        )}
        {activeTab === 'schedules' && <SchedulesPanel apps={[]} fixedApp={currentApp} compact />}
        {activeTab === 'webhooks' && <WebhooksPanel apps={[]} fixedApp={currentApp} compact />}
        {activeTab === 'run' && (
          <PromptRunner
            nodes={nodes}
            edges={edges}
            appId={currentAppId}
            appName={currentApp?.name}
            onFocusNode={onFocusNode}
            onUpdateNodeData={onUpdateNodeData}
            onConnectionsChanged={onConnectionsChanged}
          />
        )}
      </div>
    </div>
  )
}
