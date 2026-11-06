import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, tool, start, stop, slack } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-release-notes',
  name: 'Release Notes Writer',
  description: 'Reads the merged pull requests and commits from GitHub and writes user-facing release notes, then posts them to Slack.',
  badge: 'Dev Tools',
  icon: '📣',
  order: 230,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Release Notes Writer',
        'You write release notes from what was actually merged. List the merged pull requests and commits for the repo and '
        + 'range the user gives, group them under Highlights, New, Improved, Fixed and Breaking changes, and write each line '
        + 'for users with its PR number. Put breaking changes first with what users must do. Return Markdown, and post it to '
        + 'Slack when asked. Never describe a change you can\'t see in the history.',
        0.3,
      )},
      tool('tool-github', 340, 520, 'GitHub API', 'github_api', '🐙', 'Fetches repo info, PRs and commits from GitHub.',
        { github_token: '', action: 'pulls' }),
      slack('tool-slack', 600, 520, '#releases'),
      stop(700),
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-github', 'llm-1', 'tool-github'),
      edge('e-llm-slack', 'llm-1', 'tool-slack'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
