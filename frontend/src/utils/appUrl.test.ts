import { describe, expect, it } from 'vitest'
import { DEFAULT_LOCATION, buildAppUrl, parseAppUrl } from './appUrl'

describe('parseAppUrl', () => {
  it('falls back to Build with no pipeline for an empty query', () => {
    expect(parseAppUrl('')).toEqual(DEFAULT_LOCATION)
  })

  it('keeps the chat page link (?pipeline=<id>) working', () => {
    expect(parseAppUrl('?pipeline=app_123')).toMatchObject({ view: 'build', pipelineId: 'app_123' })
  })

  it('reads the tab for the view it belongs to', () => {
    expect(parseAppUrl('?view=monitor&tab=traces').monitorTab).toBe('traces')
    expect(parseAppUrl('?view=automation&tab=alerts').automationTab).toBe('alerts')
    expect(parseAppUrl('?view=settings&tab=secrets').settingsTab).toBe('secrets')
    expect(parseAppUrl('?view=build&panel=docs').panel).toBe('docs')
  })

  it('ignores unknown values', () => {
    expect(parseAppUrl('?view=nope&panel=nope')).toEqual(DEFAULT_LOCATION)
    expect(parseAppUrl('?view=monitor&tab=nope').monitorTab).toBe('runs')
  })
})

describe('buildAppUrl', () => {
  it('writes the view and its tab, and the pipeline only on Build', () => {
    expect(buildAppUrl({ ...DEFAULT_LOCATION, view: 'monitor', monitorTab: 'traces', pipelineId: 'a1' }))
      .toBe('?view=monitor&tab=traces')
  })

  it('writes the right panel tab only on Build, and only when it is not Run', () => {
    expect(buildAppUrl({ ...DEFAULT_LOCATION, pipelineId: 'a1' })).toBe('?view=build&pipeline=a1')
    expect(buildAppUrl({ ...DEFAULT_LOCATION, panel: 'docs', pipelineId: 'a1' })).toBe('?view=build&pipeline=a1&panel=docs')
    expect(buildAppUrl({ ...DEFAULT_LOCATION, view: 'apps', panel: 'docs' })).toBe('?view=apps')
  })

  it('round-trips through parseAppUrl', () => {
    const loc = { ...DEFAULT_LOCATION, view: 'settings' as const, settingsTab: 'apikeys' as const }
    expect(parseAppUrl(buildAppUrl(loc))).toEqual(loc)
    const build = { ...DEFAULT_LOCATION, panel: 'schedules' as const, pipelineId: 'x y' }
    expect(parseAppUrl(buildAppUrl(build))).toEqual(build)
    const docs = { ...DEFAULT_LOCATION, view: 'docs' as const, docPage: '03-tools' }
    expect(parseAppUrl(buildAppUrl(docs))).toEqual(docs)
  })

  it('keeps the open guide only on Docs', () => {
    expect(buildAppUrl({ ...DEFAULT_LOCATION, view: 'docs', docPage: '04-mcp' })).toBe('?view=docs&page=04-mcp')
    expect(buildAppUrl({ ...DEFAULT_LOCATION, view: 'docs' })).toBe('?view=docs')
    expect(buildAppUrl({ ...DEFAULT_LOCATION, view: 'apps', docPage: '04-mcp' })).toBe('?view=apps')
    expect(parseAppUrl('?view=build&page=04-mcp').docPage).toBeNull()
  })
})
