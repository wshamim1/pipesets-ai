import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TopNav } from './TopNav'
import type { TopView } from './TopNav'

function renderNav(view: TopView) {
  const props = {
    view, monitorTab: 'runs' as const, automationTab: 'schedules' as const,
    onViewChange: vi.fn(), onMonitorTabChange: vi.fn(), onAutomationTabChange: vi.fn(), onOpenSettings: vi.fn(),
    tenantId: 't', tenants: [], projectId: 'p', user: null, projects: [],
    onTenantChange: vi.fn(), onProjectChange: vi.fn(), onLogout: vi.fn(),
  }
  render(<TopNav {...props} />)
  return props
}

const subnavTabs = (label: string) =>
  within(screen.getByRole('navigation', { name: label })).getAllByRole('button').map((b) => b.textContent)

describe('TopNav', () => {
  it('opens Automation from the top menu', () => {
    const props = renderNav('build')
    fireEvent.click(screen.getByRole('tab', { name: 'Automation' }))
    expect(props.onViewChange).toHaveBeenCalledWith('automation')
    expect(screen.queryByRole('navigation', { name: 'Automation' })).toBeNull()   // sub-menu only on its page
  })

  it('splits unattended work (Automation) from watching runs (Monitor)', () => {
    const props = renderNav('automation')
    expect(subnavTabs('Automation')).toEqual(['Schedules', 'Webhooks', 'Batches', 'Alerts', 'Jobs'])
    fireEvent.click(screen.getByRole('button', { name: 'Jobs' }))
    expect(props.onAutomationTabChange).toHaveBeenCalledWith('jobs')
  })

  it('keeps metrics, runs, traces, logs, costs and sessions in Monitor', () => {
    renderNav('monitor')
    expect(subnavTabs('Monitor')).toEqual(['Metrics', 'Runs', 'Traces', 'Logs', 'Costs & budgets', 'Sessions'])
  })
})
