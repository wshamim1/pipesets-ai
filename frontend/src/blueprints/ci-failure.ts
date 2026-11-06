import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, slack, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-ci-failure',
  name: 'CI Failure Explainer',
  description: 'Reads the failed GitHub Actions run — jobs, failed steps and log tail — explains the first real error and the fix, and posts it to Slack.',
  badge: 'Dev Tools',
  icon: '🏗️',
  order: 290,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'CI Build Doctor',
        'You diagnose failed CI builds. List the repo\'s recent failed workflow runs (or read the one the user names), then read '
        + 'its jobs, failed steps and log tail. Find the first real error, not the cascade after it: compile error, failing test, '
        + 'dependency resolution, timeout, missing secret or flaky infrastructure. Answer with the failing step, the quoted error, '
        + 'the cause in one sentence, whether it looks flaky, and the fix. Post it to Slack when asked. Never re-run builds.',
        0.2,
      )},
      tool('tool-actions', 340, 520, 'GitHub Actions', 'github_actions', '🔁', 'Workflow runs, jobs, failed steps and logs.',
        { token: '', status: 'failure', branch: '', max_results: 10 }),
      slack('tool-slack', 600, 520, '#ci'),
      stop(700),
    ]
    const edges = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-actions', 'llm-1', 'tool-actions'),
      edge('e-llm-slack', 'llm-1', 'tool-slack'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
