import type { AppRecord } from '../types'
import { SchedulesPanel } from './SchedulesPanel'
import { WebhooksPanel } from './WebhooksPanel'
import { NotificationsPanel } from './NotificationsPanel'
import { JobsPanel } from './ops/JobsPanel'
import { BatchesPanel } from './ops/BatchesPanel'
import type { AutomationTab } from './TopNav'

interface Props {
  tab: AutomationTab
  apps: AppRecord[]
}

/** What runs unattended: schedules, webhooks, batches, alerts — and the job queue that runs them, with failures to retry. */
export function AutomationView({ tab, apps }: Props) {
  return (
    <div className="operations-view">
      {tab === 'schedules' && <SchedulesPanel apps={apps} />}
      {tab === 'webhooks'  && <WebhooksPanel apps={apps} />}
      {tab === 'batches'   && <BatchesPanel apps={apps} />}
      {tab === 'alerts'    && <NotificationsPanel apps={apps.map((a) => ({ id: a.id, name: a.name }))} />}
      {tab === 'jobs'      && <JobsPanel />}
    </div>
  )
}
