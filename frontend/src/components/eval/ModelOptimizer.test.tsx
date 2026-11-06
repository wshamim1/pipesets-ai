import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { json, sentBody, stubFetch } from '../../test/fetchStub'
import { ModelOptimizer } from './ModelOptimizer'
import type { OptimizeConfig, OptimizeStudy } from './ModelOptimizer'
import type { EvalDatasetRow } from './DatasetDetail'

let keyFor: (provider: string) => string = () => ''
vi.mock('../../context/CredentialsContext', () => ({
  useCredentials: () => ({ resolveApiKey: (p: string) => keyFor(p) }),
}))

const DATASETS: EvalDatasetRow[] = [
  { id: 'ds1', name: 'Capitals', app_id: 'app1', app_version: 0, description: '', case_count: 3, ai_count: 0, created_at: '' },
  { id: 'ds2', name: 'Loose', app_id: null, description: '', case_count: 2, ai_count: 0, created_at: '' },
]
const SLOT = { key: 'app1:a', app_id: 'app1', node_id: 'a', node_type: 'llm', label: 'Answerer',
  source: 'this pipeline', provider: 'openai', model: 'gpt-4o' }
const MODELS = { providers: [
  { id: 'openai', name: 'OpenAI', models: ['gpt-4o', 'gpt-4o-mini'] },
  { id: 'gemini', name: 'Google Gemini', models: ['gemini-3.5-flash'] },
  { id: 'mock', name: 'Mock', models: ['mock-gpt-4'] },
] }

const cfg = (extra: Partial<OptimizeConfig>): OptimizeConfig => ({
  assignment: {}, phase: 'baseline', cases: 3, pass_rate: 1, mean_score: 1, cost_per_case_usd: 0.01,
  avg_latency_ms: 900, errors: 0, meets_target: true, ...extra,
})
const MINI = { 'app1:a': { provider: 'openai', model: 'gpt-4o-mini' } }
const study = (status: OptimizeStudy['status'], extra: Partial<OptimizeStudy> = {}): OptimizeStudy => {
  const baseline = cfg({})
  const best = status === 'done' ? cfg({ assignment: MINI, phase: 'single', cost_per_case_usd: 0.0025 }) : baseline
  return {
    id: 'opt_1', app_id: 'app1', app_version: 0, dataset_id: 'ds1', status, error: null,
    request: { candidates: [{ provider: 'openai', model: 'gpt-4o-mini' }] },
    created_at: '2026-11-01T10:00:00', ...extra,
    result: status === 'queued' ? null : {
      objective: 'cost', tolerance: 0, done: status === 'done', configs_run: status === 'done' ? 2 : 1, max_configs: 40,
      truncated: false, slots: [SLOT], baseline: status === 'running' ? null : baseline, best: status === 'running' ? null : best,
      tried: status === 'done' ? [baseline, best] : status === 'running' ? [] : [baseline], planned_configs: 2,
      current: status === 'running'
        ? { assignment: {}, phase: 'baseline', index: 0, cases_done: 1, cases_total: 3, passed: 1, cost_usd: 0.012, latency_ms: 900 }
        : null,
      warnings: [],
    },
  }
}

const label = (id: string | null | undefined, v?: number) => (id ? `Capitals bot ${v ? `v${v}` : 'draft'}` : null)

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  keyFor = () => ''
  localStorage.clear()
})

describe('ModelOptimizer', () => {
  it('runs a study, polls it to the end and applies the winner', async () => {
    let finish = false
    const fetch = stubFetch({
      'GET /api/models': MODELS,
      'POST /api/eval/optimize-models/slots': { slots: [SLOT], errors: [] },
      'GET /api/eval/optimizations': [],
      'POST /api/eval/optimize-models': study('queued'),
      'GET /api/eval/optimizations/opt_1': () => (finish ? study('done') : study('running')),
      'GET /api/eval/optimizations/opt_1/cases': (_i: unknown, url: string) => [{
        case_id: 'c1', prompt: 'Capital of France?', expected_output: 'paris', score: 1, passed: true,
        cost_usd: 0.012, latency_ms: 900, error: null,
        output: new URL(url).searchParams.get('config') === '1' ? 'It is Paris.' : 'Paris',
      }],
      'POST /api/eval/optimizations/opt_1/apply': {
        applied: [{ key: 'app1:a', label: 'Answerer', provider: 'openai', model: 'gpt-4o-mini' }], skipped: [] },
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ModelOptimizer datasets={DATASETS} pipelineLabel={label} pollMs={5} />)

    // only linked datasets are offered
    const select = screen.getByLabelText('Dataset')
    expect([...select.querySelectorAll('option')].map((o) => o.textContent)).toEqual([
      '— select dataset —', 'Capitals · Capitals bot draft (3 cases)'])
    fireEvent.change(select, { target: { value: 'ds1' } })
    expect(await screen.findByText('Answerer')).toBeTruthy()

    // mock models aren't offered; a node's own model may be picked but the backend skips it
    expect(screen.queryByText('mock-gpt-4')).toBeNull()
    const start = screen.getByRole('button', { name: '⚡ Optimize models' }) as HTMLButtonElement
    expect(start.disabled).toBe(true)
    fireEvent.click(await screen.findByLabelText('gpt-4o-mini'))
    fireEvent.change(screen.getByLabelText('Pass rate it may lose'), { target: { value: '5' } })
    expect(screen.getByText(/Up to 2 configs · about 6 pipeline runs/)).toBeTruthy()
    // screening more cases than the dataset has is off, so it adds no configs
    fireEvent.change(screen.getByLabelText('Screen on first'), { target: { value: '5' } })
    expect(screen.getByText(/Up to 2 configs · about 6 pipeline runs/)).toBeTruthy()
    expect(screen.getByText(/so it stays off/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Screen on first'), { target: { value: '0' } })
    fireEvent.click(start)

    expect(await screen.findByText(/Trying the saved models · case 2 of 3/)).toBeTruthy()
    expect(screen.getByRole('status').textContent).toMatch(/^Running1 of ~2 configs/)
    expect(screen.getByText(/1\/1 passing so far · \$0.0120\/case/)).toBeTruthy()
    expect(screen.getByText(/Plan: saved models → 1 single swap \(1 node × 1 model\)/)).toBeTruthy()
    // the running config is a row too, and opens its cases so far
    fireEvent.click(screen.getByText(/Saved models · running/))
    expect(await screen.findByText('Paris')).toBeTruthy()
    // the history row follows the open study
    expect(screen.getAllByText('Running').length).toBeGreaterThan(1)
    finish = true
    await screen.findByText('Recommended')
    expect(screen.getByRole('status').textContent).toMatch(/^Done2 configs/)
    expect(sentBody(fetch, 'POST /api/eval/optimize-models')).toMatchObject({
      app_id: 'app1', dataset_id: 'ds1', objective: 'cost', tolerance: 0.05,
      candidates: [{ provider: 'openai', model: 'gpt-4o-mini' }],
    })
    expect(screen.getByText('Answerer → openai/gpt-4o-mini', { selector: '.opt-changes div' })).toBeTruthy()
    expect(screen.getByText(/75% cheaper/)).toBeTruthy()
    expect(screen.getByText(/One swap ★/)).toBeTruthy()
    fireEvent.click(screen.getByText(/One swap ★/))
    expect(await screen.findByText('It is Paris.')).toBeTruthy()
    expect(screen.getByText('Expected: paris')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Apply to draft' }))
    expect(await screen.findByText('Applied to the draft: Answerer → gpt-4o-mini.')).toBeTruthy()
  })

  it('shows the live status in history, says no winner yet, and shows old stopped studies as cancelled', async () => {
    const live = study('running')
    live.result!.baseline = cfg({})
    live.result!.best = cfg({})
    // stopped through the jobs API before the cancel endpoint: saved as failed with "Cancelled"
    const stopped = { ...live, status: 'failed' as const, error: 'Cancelled' }
    let finished = false
    stubFetch({
      'GET /api/models': MODELS,
      'POST /api/eval/optimize-models/slots': { slots: [SLOT], errors: [] },
      'GET /api/eval/optimizations': () => (finished ? [stopped] : []),
      'POST /api/eval/optimize-models': study('queued'),
      'GET /api/eval/optimizations/opt_1': () => (finished ? stopped : live),
    })
    render(<ModelOptimizer datasets={DATASETS} pipelineLabel={label} pollMs={5} />)
    fireEvent.change(screen.getByLabelText('Dataset'), { target: { value: 'ds1' } })
    fireEvent.click(await screen.findByLabelText('gpt-4o-mini'))
    fireEvent.click(screen.getByRole('button', { name: '⚡ Optimize models' }))

    // the row added as Queued picks up the running status from the poll
    await waitFor(() => expect(screen.getAllByText('Running')).toHaveLength(2))
    expect(screen.getByText('No winner yet — still trying models.')).toBeTruthy()
    expect(screen.queryByText(/No model beat the saved ones/)).toBeNull()

    finished = true
    await waitFor(() => expect(screen.getAllByText('Cancelled')).toHaveLength(2))
    expect(screen.queryByText('Failed')).toBeNull()
  })

  it('offers providers with a key first and shows why every case failed', async () => {
    keyFor = (p) => (p === 'openai' ? 'secret://sec_1' : '')
    const failed = study('done')
    failed.result!.tried[1] = { ...failed.result!.tried[1], errors: 3, pass_rate: 0, first_error: 'HTTP 401: bad key' }
    stubFetch({
      'GET /api/models': MODELS,
      'POST /api/eval/optimize-models/slots': { slots: [SLOT], errors: [] },
      'GET /api/eval/optimizations': [failed],
    })
    render(<ModelOptimizer datasets={DATASETS} pipelineLabel={label} />)
    expect(await screen.findByText('OpenAI')).toBeTruthy()
    expect(screen.queryByText('Google Gemini')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Show all providers (1 more without a key)' }))
    expect(screen.getByText('Google Gemini')).toBeTruthy()

    fireEvent.change(screen.getByLabelText('Dataset'), { target: { value: 'ds1' } })
    // the latest study opens by itself
    expect(await screen.findByText('⚠ Some cases failed: HTTP 401: bad key')).toBeTruthy()
  })

  it('warns and hides Apply when the saved models pass nothing', async () => {
    const blind = study('done')
    blind.result!.baseline = cfg({ pass_rate: 0 })
    blind.result!.best = cfg({ assignment: MINI, phase: 'single', pass_rate: 0, cost_per_case_usd: 0.001 })
    stubFetch({
      'GET /api/models': MODELS,
      'POST /api/eval/optimize-models/slots': { slots: [SLOT], errors: [] },
      'GET /api/eval/optimizations': [blind],
    })
    render(<ModelOptimizer datasets={DATASETS} pipelineLabel={label} />)
    fireEvent.change(screen.getByLabelText('Dataset'), { target: { value: 'ds1' } })
    fireEvent.click(await screen.findByRole('button', { name: /no quality signal/ }))
    expect(screen.getByRole('alert').textContent).toMatch(/don't apply it/)
    expect(screen.queryByRole('button', { name: 'Apply to draft' })).toBeNull()
  })

  it('lists recent optimizations without a dataset, re-runs one and loads another into the form', async () => {
    const old = study('done', { id: 'opt_old', request: { scorer: 'llm_judge', objective: 'cost', tolerance: 0.1,
      max_configs: 12, candidates: [{ provider: 'openai', model: 'gpt-4o-mini' }] } })
    const fetch = stubFetch({
      'GET /api/models': MODELS,
      'POST /api/eval/optimize-models/slots': { slots: [SLOT], errors: [] },
      'GET /api/eval/optimizations': [old],
      'POST /api/eval/optimize-models': study('queued', { id: 'opt_new' }),
      'GET /api/eval/optimizations/opt_new': study('queued', { id: 'opt_new' }),
    })
    render(<ModelOptimizer datasets={DATASETS} pipelineLabel={label} />)
    expect(await screen.findByText('Recent optimizations (1)')).toBeTruthy()
    expect(screen.getByText('Capitals · Capitals bot draft')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /^Edit and re-run/ }))
    expect((screen.getByLabelText('Dataset') as HTMLSelectElement).value).toBe('ds1')
    expect((screen.getByLabelText('Scorer') as HTMLSelectElement).value).toBe('llm_judge')
    expect((screen.getByLabelText('Pass rate it may lose') as HTMLInputElement).value).toBe('10')
    expect((await screen.findByLabelText('gpt-4o-mini') as HTMLInputElement).checked).toBe(true)
    expect(screen.getByText('Recommended')).toBeTruthy()          // the old study is open

    fireEvent.click(screen.getByRole('button', { name: '↻ Re-run' }))
    await waitFor(() => expect(sentBody(fetch, 'POST /api/eval/optimize-models')).toMatchObject({
      app_id: 'app1', dataset_id: 'ds1', scorer: 'llm_judge', tolerance: 0.1, max_configs: 12,
      candidates: [{ provider: 'openai', model: 'gpt-4o-mini' }],
    }))
    expect(await screen.findByText('Waiting for a worker…')).toBeTruthy()
    expect(localStorage.getItem('pipesets.optimize.dataset')).toBe('ds1')
  })

  it('optimizes only the ticked nodes, in parallel, and can be cancelled', async () => {
    const WRITER = { ...SLOT, key: 'app1:w', node_id: 'w', label: 'Writer' }
    const running = { ...study('running'), request: { candidates: [{ provider: 'openai', model: 'gpt-4o-mini' }], slot_keys: ['app1:w'] } }
    const fetch = stubFetch({
      'GET /api/models': MODELS,
      'POST /api/eval/optimize-models/slots': { slots: [SLOT, WRITER], errors: [] },
      'GET /api/eval/optimizations': [],
      'POST /api/eval/optimize-models': running,
      'GET /api/eval/optimizations/opt_1': running,
      'POST /api/eval/optimizations/opt_1/cancel': { ...running, status: 'cancelled', error: 'Cancelled' },
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<ModelOptimizer datasets={DATASETS} pipelineLabel={label} pollMs={60_000} />)
    fireEvent.change(screen.getByLabelText('Dataset'), { target: { value: 'ds1' } })
    fireEvent.click(await screen.findByLabelText('Optimize Answerer'))      // leave the Answerer as it is
    expect(screen.getByText('Nodes to optimize (1 of 2)')).toBeTruthy()
    fireEvent.click(await screen.findByLabelText('gpt-4o-mini'))
    fireEvent.change(screen.getByLabelText('Cases at once'), { target: { value: '8' } })
    fireEvent.click(screen.getByRole('button', { name: '⚡ Optimize models' }))

    await waitFor(() => expect(sentBody(fetch, 'POST /api/eval/optimize-models')).toMatchObject({
      slot_keys: ['app1:w'], parallel: 8 }))
    fireEvent.click(await screen.findByRole('button', { name: '■ Cancel' }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/^Cancelled.*Stopped by you after 1 configs/))
    expect(screen.queryByRole('button', { name: '■ Cancel' })).toBeNull()
  })

  it('shows why a study could not start', async () => {
    stubFetch({
      'GET /api/models': MODELS,
      'POST /api/eval/optimize-models/slots': { slots: [SLOT], errors: [] },
      'GET /api/eval/optimizations': [],
      'POST /api/eval/optimize-models': () => json({ detail: 'Dataset not found' }, 404),
    })
    render(<ModelOptimizer datasets={DATASETS} pipelineLabel={label} />)
    fireEvent.change(screen.getByLabelText('Dataset'), { target: { value: 'ds1' } })
    fireEvent.click(await screen.findByLabelText('gpt-4o-mini'))
    await screen.findByText('Answerer')
    fireEvent.click(screen.getByRole('button', { name: '⚡ Optimize models' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Dataset not found/))
  })

  it('opens the latest optimization and shows why it failed', async () => {
    stubFetch({
      'GET /api/models': MODELS,
      'POST /api/eval/optimize-models/slots': { slots: [SLOT], errors: [] },
      'GET /api/eval/optimizations': [study('failed', { error: 'No candidate model can run' })],
    })
    render(<ModelOptimizer datasets={DATASETS} pipelineLabel={label} />)
    fireEvent.change(screen.getByLabelText('Dataset'), { target: { value: 'ds1' } })
    expect(await screen.findByText('No candidate model can run', { selector: '.opt-status-card *' })).toBeTruthy()
    expect(screen.getByRole('status').textContent).toMatch(/^Failed/)
  })
})
