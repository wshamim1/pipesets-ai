// The builder's navigation lives in the query string so a refresh (or a shared link)
// lands on the same view, tab and pipeline: /?view=build&pipeline=<id>&panel=docs
// Query params, not paths, so it works behind any static server without rewrites.

export const TOP_VIEWS = ['apps', 'build', 'evaluate', 'monitor', 'automation', 'marketplace', 'lab', 'settings', 'docs'] as const
export const MONITOR_TABS = ['metrics', 'runs', 'traces', 'logs', 'costs', 'sessions'] as const
export const AUTOMATION_TABS = ['schedules', 'webhooks', 'batches', 'alerts', 'jobs'] as const
export const SETTINGS_TABS = ['members', 'workspaces', 'apikeys', 'audit', 'providerkeys', 'backends', 'secrets', 'packages', 'agents', 'admin', 'database', 'tunnel', 'system', 'danger'] as const
export const RIGHT_PANEL_TABS = ['run', 'overview', 'docs', 'schedules', 'webhooks'] as const

export type TopView = typeof TOP_VIEWS[number]
export type MonitorTab = typeof MONITOR_TABS[number]
export type AutomationTab = typeof AUTOMATION_TABS[number]
export type SettingsTab = typeof SETTINGS_TABS[number]
export type RightPanelTab = typeof RIGHT_PANEL_TABS[number]

export interface AppLocation {
  view: TopView
  monitorTab: MonitorTab
  automationTab: AutomationTab
  settingsTab: SettingsTab
  panel: RightPanelTab
  pipelineId: string | null
  /** Docs: the open guide's id (its file name without .md); the section rides in the URL's #hash */
  docPage: string | null
}

export const DEFAULT_LOCATION: AppLocation = {
  view: 'build',
  monitorTab: 'runs',
  automationTab: 'schedules',
  settingsTab: 'members',
  panel: 'run',
  pipelineId: null,
  docPage: null,
}

const pick = <T extends string>(allowed: readonly T[], value: string | null, fallback: T): T =>
  allowed.includes(value as T) ? (value as T) : fallback

/** Read the location from a query string; unknown or missing values fall back to the defaults. */
export function parseAppUrl(search: string): AppLocation {
  const q = new URLSearchParams(search)
  const view = pick(TOP_VIEWS, q.get('view'), DEFAULT_LOCATION.view)
  const tab = q.get('tab')
  return {
    view,
    monitorTab: view === 'monitor' ? pick(MONITOR_TABS, tab, DEFAULT_LOCATION.monitorTab) : DEFAULT_LOCATION.monitorTab,
    automationTab: view === 'automation' ? pick(AUTOMATION_TABS, tab, DEFAULT_LOCATION.automationTab) : DEFAULT_LOCATION.automationTab,
    settingsTab: view === 'settings' ? pick(SETTINGS_TABS, tab, DEFAULT_LOCATION.settingsTab) : DEFAULT_LOCATION.settingsTab,
    panel: pick(RIGHT_PANEL_TABS, q.get('panel'), DEFAULT_LOCATION.panel),
    pipelineId: q.get('pipeline') || null,
    docPage: view === 'docs' ? q.get('page') || null : null,
  }
}

/** The query string for a location: only the tab of the current view; the pipeline and panel only on
 * Build; the guide only on Docs. */
export function buildAppUrl(loc: AppLocation): string {
  const q = new URLSearchParams({ view: loc.view })
  const tab = loc.view === 'monitor' ? loc.monitorTab
    : loc.view === 'automation' ? loc.automationTab
    : loc.view === 'settings' ? loc.settingsTab
    : null
  if (tab) q.set('tab', tab)
  if (loc.view === 'build') {
    if (loc.pipelineId) q.set('pipeline', loc.pipelineId)
    if (loc.panel !== DEFAULT_LOCATION.panel) q.set('panel', loc.panel)
  }
  if (loc.view === 'docs' && loc.docPage) q.set('page', loc.docPage)
  return `?${q.toString()}`
}
