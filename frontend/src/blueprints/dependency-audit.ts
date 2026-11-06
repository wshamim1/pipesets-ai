import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, start, stop, tool } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-dependency-audit',
  name: 'Dependency Audit',
  description: 'Checks a requirements.txt or package.json against PyPI and npm: outdated majors, abandoned packages and licences that may block commercial use.',
  badge: 'Dev Tools',
  icon: '📦',
  order: 310,
  build() {
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: llm(
        'Dependency Checker',
        'You review a project\'s dependencies. Take the list the user pastes, or read the dependency file from the repo. For each '
        + 'package look up the latest version, release date and licence. Flag major versions behind, no release in 2+ years, and '
        + 'GPL / AGPL licences. Return a table (package, current, latest, released, licence, note) and the upgrades to do first. '
        + 'Never change files or open pull requests.',
        0.2,
      )},
      tool('tool-pkg', 340, 520, 'Package Info', 'package_info', '📦', 'Latest version, licence and requirements on PyPI and npm.',
        { registry: 'auto' }),
      tool('tool-github', 600, 520, 'GitHub API', 'github_api', '🐙', 'Reads the dependency file from a repo.',
        { github_token: '', action: 'repo_info' }),
      stop(700),
    ]
    const edges = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-llm-pkg', 'llm-1', 'tool-pkg'),
      edge('e-llm-github', 'llm-1', 'tool-github'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
