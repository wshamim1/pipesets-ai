import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { json, stubFetch } from '../../test/fetchStub'
import { MetricsPanel } from './MetricsPanel'
import type { MetricsOverview } from './MetricsPanel'

const point = (h: number, runs: number, failed = 0, p95: number | null = null) => ({
  t: `2026-10-31T${String(h).padStart(2, '0')}:00:00Z`, runs, failed, p95_ms: p95, cost_usd: 0, tokens: 0,
})

const overview = (over: Partial<MetricsOverview> = {}): MetricsOverview => ({
  hours: 24, bucket_seconds: 3600, truncated: false,
  totals: { runs: 4, failed: 1, error_rate: 0.25, p50_ms: 150, p95_ms: 2400, cost_usd: 0.03, tokens: 150, simulated: 1 },
  series: [point(10, 0), point(11, 3, 1, 2400), point(12, 1, 0, 90)],
  models: [{ provider: 'openai', model: 'gpt-x', runs: 3, failed: 1, p95_ms: 2400, cost_usd: 0.03, tokens: 150 }],
  tools: [{ name: 'web_search', calls: 2, failed: 1, p95_ms: 30 }],
  phases: [{ phase: 'retrieval', count: 1, p95_ms: 40, total_ms: 40 }],
  agent_runs: { total: 0, by_status: {} },
  queue: { queued: 2, running: 0, dead: 1, oldest_wait_s: 95 },
  ...over,
})

describe('MetricsPanel', () => {
  it('shows totals, both charts and the breakdowns', async () => {
    stubFetch({ 'GET /api/metrics/overview': overview() })
    render(<MetricsPanel apps={[]} />)

    expect(await screen.findByText('25%')).toBeTruthy()            // error rate
    expect(screen.getByText('p95 latency').previousSibling?.textContent).toBe('2.4s')
    expect(screen.getByText(/oldest 2m · 1 dead/)).toBeTruthy()
    expect(screen.getByText(/1 of these runs were simulated/)).toBeTruthy()
    expect(screen.getByRole('img', { name: 'Runs per interval, 4 in total' })).toBeTruthy()
    expect(screen.getByRole('img', { name: 'p95 run latency per interval' })).toBeTruthy()
    expect(screen.getByText('openai/gpt-x')).toBeTruthy()
    expect(screen.getByText('web_search')).toBeTruthy()
    expect(screen.getByText('retrieval')).toBeTruthy()
  })

  it('refetches for another window and pipeline', async () => {
    const mock = stubFetch({ 'GET /api/metrics/overview': overview() })
    render(<MetricsPanel apps={[{ id: 'a1', name: 'Support bot' }]} />)
    await screen.findByText('25%')

    fireEvent.change(screen.getByRole('combobox', { name: 'Time window' }), { target: { value: '168' } })
    fireEvent.change(screen.getByRole('combobox', { name: 'Pipeline' }), { target: { value: 'a1' } })
    await screen.findByText('25%')
    const last = new URL(String(mock.mock.calls.at(-1)![0]))
    expect(last.searchParams.get('hours')).toBe('168')
    expect(last.searchParams.get('app_id')).toBe('a1')
  })

  it('says so when the window has no runs', async () => {
    stubFetch({ 'GET /api/metrics/overview': overview({
      totals: { runs: 0, failed: 0, error_rate: null, p50_ms: null, p95_ms: null, cost_usd: 0, tokens: 0, simulated: 0 },
      series: [point(10, 0)], models: [], tools: [], phases: [],
    }) })
    render(<MetricsPanel apps={[]} />)
    expect(await screen.findByText(/No runs in this window/)).toBeTruthy()
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('reports a failed load with a retry', async () => {
    stubFetch({ 'GET /api/metrics/overview': json({ detail: 'nope' }, 500) })
    render(<MetricsPanel apps={[]} />)
    expect((await screen.findByRole('alert')).textContent).toMatch(/HTTP 500/)
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
  })
})
