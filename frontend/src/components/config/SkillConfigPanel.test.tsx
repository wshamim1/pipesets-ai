import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { stubFetch } from '../../test/fetchStub'
import type { FlowNode } from '../../types'
import { SkillConfigPanel } from './SkillConfigPanel'

const node = (data: Record<string, unknown>) => ({ id: 'sk', type: 'skill', position: { x: 0, y: 0 }, data }) as unknown as FlowNode
const props = { onDelete: vi.fn(), onSave: vi.fn() }

beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })

describe('SkillConfigPanel', () => {
  it('shows a library skill read-only and pins a version', async () => {
    stubFetch({
      'GET /api/skills/skill_custom_1': { id: 'skill_custom_1', name: 'Refunds', icon: '💸', version: 3,
        when_to_use: 'When the user asks about a refund.', required_tools: ['calculator'], instructions: 'V3 RULES',
        description: '', tool_ids: ['calculator'], tags: [], category: 'general', created_at: '', updated_at: '' },
      'GET /api/skills/skill_custom_1/versions': [
        { version: 3, created_at: '2026-11-03T10:00:00' }, { version: 2, created_at: '2026-11-02T10:00:00' }],
    })
    const onUpdate = vi.fn()
    render(<SkillConfigPanel activeNode={node({ label: 'Refunds', skill_id: 'skill_custom_1', instructions: 'STALE' })}
      onUpdate={onUpdate} {...props} />)
    expect(await screen.findByText('V3 RULES')).toBeTruthy()
    expect(screen.queryByText('STALE')).toBeNull()
    expect(screen.getByText('When the user asks about a refund.')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Version'), { target: { value: '2' } })
    expect(onUpdate).toHaveBeenCalledWith('sk', { skill_version: 2 })
  })

  it('edits the node’s own copy when the skill is gone from the library', async () => {
    stubFetch({ 'GET /api/skills/gone': () => new Response('{}', { status: 404 }),
                'GET /api/skills/gone/versions': () => new Response('[]', { status: 404 }) })
    render(<SkillConfigPanel activeNode={node({ label: 'Old', skill_id: 'gone', description: 'When asked.' })}
      onUpdate={vi.fn()} {...props} />)
    expect(await screen.findByText(/isn't in the project's library any more/)).toBeTruthy()
    expect(screen.getByText('When the user asks to… (11 / 300)')).toBeTruthy()
  })
})
