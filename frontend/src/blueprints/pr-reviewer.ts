import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-pr-reviewer',
  name: 'GitHub PR Reviewer',
  description: 'Fetches pull requests and diffs from GitHub and returns a structured review of bugs, risks, and test gaps.',
  badge: 'Dev Tools',
  icon: '🐙',
  order: 90,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 60, y: 300 }, data: { label: 'Start' } },
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Code Reviewer',
        'You are a senior code reviewer. Fetch the pull request and its changed files, then report: '
        + '1) likely bugs, 2) security or performance risks, 3) missing tests, 4) a short overall verdict. '
        + 'Quote file paths and lines; skip style nitpicks.',
        0.2,
      )},
      { id: 'tool-github', type: 'tool', position: { x: 340, y: 520 }, data: {
        label: 'GitHub API', toolId: 'github_api', toolType: 'tool', icon: '🐙',
        description: 'Fetch repo info, issues, PRs, commits, or file contents from GitHub.',
        config: { github_token: '', action: 'repo_info' },
      }},
      { id: 'stop-1', type: 'stop', position: { x: 700, y: 300 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-github', 'llm-1', 'tool-github'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
