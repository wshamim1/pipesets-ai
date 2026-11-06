import type { AppRecord } from '../types'
import { GlobalRunsPanel } from './ops/GlobalRunsPanel'
import { GlobalTracesPanel } from './ops/GlobalTracesPanel'
import { GlobalLogsPanel } from './ops/GlobalLogsPanel'
import { CostSummaryPanel } from './ops/CostSummaryPanel'
import { MetricsPanel } from './ops/MetricsPanel'
import { MemoryInspectorPanel } from './MemoryInspectorPanel'
import type { MonitorTab } from './TopNav'

interface Props {
  tab: MonitorTab
  apps: AppRecord[]
}

/** Runtime view of every pipeline: metrics, runs, traces, logs, spend and conversation sessions. Schedules, webhooks and alerts are under Automation. */
export function MonitorView({ tab, apps }: Props) {
  const simpleApps = apps.map((a) => ({ id: a.id, name: a.name }))

  return (
    <div className="operations-view">
      {tab === 'metrics'  && <MetricsPanel apps={simpleApps} />}
      {tab === 'runs'     && <GlobalRunsPanel apps={simpleApps} />}
      {tab === 'traces'   && <GlobalTracesPanel apps={simpleApps} />}
      {tab === 'logs'     && <GlobalLogsPanel apps={simpleApps} />}
      {tab === 'costs'    && <CostSummaryPanel apps={simpleApps} />}
      {tab === 'sessions' && <MemoryInspectorPanel />}
    </div>
  )
}
