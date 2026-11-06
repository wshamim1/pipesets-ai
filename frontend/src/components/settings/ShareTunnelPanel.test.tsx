import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { json, sentBody, stubFetch } from '../../test/fetchStub'
import { ShareTunnelPanel } from './ShareTunnelPanel'
import type { TunnelStatus } from './ShareTunnelPanel'

const URL = 'https://calm-otter.ngrok-free.app'
const status = (over: Partial<TunnelStatus> = {}): TunnelStatus => ({
  enabled: true, installed: true, port: '5173', running: false, ours: false, domain: null,
  public_url: null, inspect_url: null, ...over,
})

describe('ShareTunnelPanel', () => {
  beforeEach(() => localStorage.clear())

  it('starts a tunnel on the static domain and shows its address', async () => {
    const mock = stubFetch({
      'GET /api/dev/tunnel': status(),
      'POST /api/dev/tunnel/start': status({ running: true, ours: true, domain: 'calm-otter.ngrok-free.app',
                                             public_url: URL, inspect_url: 'http://127.0.0.1:4040' }),
    })
    render(<ShareTunnelPanel />)
    fireEvent.change(await screen.findByPlaceholderText('your-name.ngrok-free.app'), { target: { value: ' calm-otter.ngrok-free.app ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start tunnel' }))

    expect(await screen.findByRole('link', { name: URL })).toBeTruthy()
    expect(sentBody(mock, 'POST /api/dev/tunnel/start')).toEqual({ domain: 'calm-otter.ngrok-free.app' })
    expect(localStorage.getItem('pipesets.ngrokDomain')).toBe('calm-otter.ngrok-free.app')
    expect(screen.getByRole('button', { name: 'Stop tunnel' })).toBeTruthy()
  })

  it('shows a terminal-started tunnel without offering to stop it', async () => {
    stubFetch({ 'GET /api/dev/tunnel': status({ running: true, public_url: URL }) })
    render(<ShareTunnelPanel />)
    expect(await screen.findByText(/started from a terminal/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Stop tunnel' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Start tunnel' })).toBeNull()
  })

  it("explains when tunnels are off and doesn't offer to start one", async () => {
    stubFetch({ 'GET /api/dev/tunnel': status({ enabled: false }) })
    render(<ShareTunnelPanel />)
    expect(await screen.findByText(/Tunnels are off on this server/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start tunnel' })).toBeNull()
  })

  it("shows ngrok's own error when it fails to start", async () => {
    stubFetch({
      'GET /api/dev/tunnel': status(),
      'POST /api/dev/tunnel/start': json({ detail: "ngrok didn't start:\nERR_NGROK_320: the domain is not yours" }, 502),
    })
    render(<ShareTunnelPanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Start tunnel' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/ERR_NGROK_320/)
  })
})
