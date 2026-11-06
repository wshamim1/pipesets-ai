import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CustomMcpModal } from './CustomMcpModal'

const AWS = JSON.stringify({
  mcpServers: {
    'aws-mcp': {
      command: 'uvx', timeout: 100000, transport: 'stdio',
      args: ['mcp-proxy-for-aws@1.6.3', 'https://aws-mcp.us-east-1.api.aws/mcp', '--metadata', 'AWS_REGION=us-west-2'],
    },
  },
})

const paste = (text: string) => {
  fireEvent.click(screen.getByText('Paste JSON config'))
  fireEvent.change(screen.getByPlaceholderText(/"mcpServers"/), { target: { value: text } })
  fireEvent.click(screen.getByText('Fill in the form'))
}

afterEach(() => vi.unstubAllGlobals())

describe('CustomMcpModal — paste JSON config', () => {
  it('fills the form from an mcpServers block and sends the same args to the server', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, tool_count: 0, tools: [] }) })
    vi.stubGlobal('fetch', fetchMock)
    render(<CustomMcpModal onSaved={() => {}} onClose={() => {}} />)
    paste(AWS)

    expect(screen.getByDisplayValue('aws-mcp')).toBeTruthy()
    expect(screen.getByDisplayValue('uvx')).toBeTruthy()
    expect(screen.getByDisplayValue(/mcp-proxy-for-aws@1.6.3 https:\/\/aws-mcp/)).toBeTruthy()
    expect(screen.getByText(/Not used: timeout/)).toBeTruthy()

    fireEvent.click(screen.getByText('Test connection'))
    await screen.findByText(/Connected!/)
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body).toMatchObject({ transport: 'stdio', command: 'uvx',
      args: ['mcp-proxy-for-aws@1.6.3', 'https://aws-mcp.us-east-1.api.aws/mcp', '--metadata', 'AWS_REGION=us-west-2'] })
  })

  it('switches to HTTP for a remote server and says what is wrong with a bad paste', () => {
    render(<CustomMcpModal onSaved={() => {}} onClose={() => {}} />)
    paste('{"mcpServers": {"remote": {"url": "https://example.com/mcp"}}}')
    expect(screen.getByDisplayValue('https://example.com/mcp')).toBeTruthy()
    expect(screen.getByText(/HTTP transport/)).toBeTruthy()

    paste('{"mcpServers": {}}')
    expect(screen.getByText(/No MCP server found/)).toBeTruthy()
  })
})

const value = (placeholder: string) => (screen.getByPlaceholderText(placeholder) as HTMLInputElement).value

describe('CustomMcpModal — templates', () => {
  it('fills a remote server with its URL and token header, and clears the header for the next one', () => {
    render(<CustomMcpModal onSaved={() => {}} onClose={() => {}} />)
    fireEvent.click(screen.getByText('GitHub'))
    expect(value('http://localhost:8000/sse or https://api.example.com/mcp')).toBe('https://api.githubcopilot.com/mcp/')
    expect(JSON.parse(value('{ "Authorization": "Bearer sk-..." }'))).toEqual({
      Authorization: 'Bearer <GitHub personal access token>', 'X-MCP-Readonly': 'true',
    })

    fireEvent.click(screen.getByText('Postgres'))
    expect(value('npx, uvx, python')).toBe('uvx')
    expect(value('-y some-mcp-server@1.2.3 --flag')).toBe('postgres-mcp@0.3.0 --access-mode=restricted')
    // the DSN goes in env, not in the arguments
    expect(JSON.parse(value('{ "DB_PASSWORD": "secret", "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..." }')))
      .toEqual({ DATABASE_URI: 'postgresql://localhost/mydb' })

    fireEvent.click(screen.getByText('Linear'))
    expect(JSON.parse(value('{ "Authorization": "Bearer sk-..." }'))).toEqual({ Authorization: 'Bearer <Linear API key>' })
    fireEvent.click(screen.getByText('Remote'))
    expect(value('{ "Authorization": "Bearer sk-..." }')).toBe('{}')
  })
})
