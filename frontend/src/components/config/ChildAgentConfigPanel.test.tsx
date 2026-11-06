import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { sentBody, stubFetch } from '../../test/fetchStub'
import { agent } from '../../test/agentFixtures'
import type { FlowNode } from '../../types'
import { setAgentCatalog } from '../../utils/agentCatalog'
import { ChildAgentConfigPanel } from './ChildAgentConfigPanel'

const node = (data: Record<string, unknown>) => ({
  id: 'c', type: 'child_agent', position: { x: 0, y: 0 },
  data: { label: 'SQL Analyst Agent', master_id: '', role: 'SQL Analyst', provider: 'openai', model: 'gpt-4o',
    api_key: '', allowed_tool_ids: [], system_prompt: 'Write SQL.', ...data },
}) as unknown as FlowNode

describe('ChildAgentConfigPanel — built-in eval set', () => {
  it('copies a dropped built-in agent\'s eval set into a dataset for this pipeline', async () => {
    const fetchMock = stubFetch({
      'GET /api/saved-agents': [],
      'POST /api/agent-catalog/sql_analyst/eval-dataset': { dataset_id: 'd1', name: 'SQL Analyst — built-in eval', cases_created: 6, scorer: 'llm_judge' },
    })
    setAgentCatalog({ groups: ['Data platform'], can_edit: true, can_install_tools: true,
      agents: [agent({ id: 'sql_analyst', name: 'SQL Analyst', role: 'SQL Analyst', starter: false, eval_cases: 6 })] })
    render(<ChildAgentConfigPanel activeNode={node({ builtin_agent_id: 'sql_analyst' })} onUpdate={vi.fn()} onDelete={vi.fn()}
      onSave={vi.fn()} currentAppId="app-9" />)

    expect(screen.getByText(/comes with 6 test cases/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Create eval dataset' }))
    await waitFor(() => expect(screen.getByText(/Created “SQL Analyst — built-in eval” with 6 cases/)).toBeTruthy())
    expect(sentBody(fetchMock, 'POST /api/agent-catalog/sql_analyst/eval-dataset')).toEqual({ app_id: 'app-9' })
  })

  it('has no eval set for a child that isn\'t from a tool-backed built-in', () => {
    stubFetch({ 'GET /api/saved-agents': [] })
    setAgentCatalog({ groups: [], can_edit: true, can_install_tools: true, agents: [agent({})] })
    render(<ChildAgentConfigPanel activeNode={node({ builtin_agent_id: 'starter_researcher' })} onUpdate={vi.fn()}
      onDelete={vi.fn()} onSave={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Create eval dataset' })).toBeNull()
  })
})
