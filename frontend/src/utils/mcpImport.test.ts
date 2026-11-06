import { describe, expect, it } from 'vitest'
import { joinArgs, parseMcpConfig, splitArgs } from './mcpImport'

describe('parseMcpConfig', () => {
  it('reads the mcpServers format (Claude Desktop / Cursor / AWS)', () => {
    const r = parseMcpConfig(JSON.stringify({
      mcpServers: {
        'aws-mcp': {
          command: 'uvx', timeout: 100000, transport: 'stdio',
          args: ['mcp-proxy-for-aws@1.6.3', 'https://aws-mcp.us-east-1.api.aws/mcp', '--metadata', 'AWS_REGION=us-west-2'],
        },
      },
    }))
    expect(r.server).toEqual({
      name: 'aws-mcp', transport: 'stdio', command: 'uvx',
      args: ['mcp-proxy-for-aws@1.6.3', 'https://aws-mcp.us-east-1.api.aws/mcp', '--metadata', 'AWS_REGION=us-west-2'],
      env_vars: {}, url: '', headers: {},
    })
    expect(r.ignored).toEqual(['timeout'])
    expect(r.others).toEqual([])
  })

  it('reads VS Code servers, remote servers and env values', () => {
    const r = parseMcpConfig(JSON.stringify({
      servers: {
        github: { type: 'http', url: 'https://api.githubcopilot.com/mcp/', headers: { Authorization: 'Bearer x' } },
        pg: { command: 'npx', args: ['-y', 'server-postgres'], env: { PORT: 5432 } },
      },
    }))
    expect(r.server).toMatchObject({ name: 'github', transport: 'http', url: 'https://api.githubcopilot.com/mcp/',
                                     headers: { Authorization: 'Bearer x' } })
    expect(r.others).toEqual(['pg'])
    expect(parseMcpConfig(JSON.stringify({ pg: { command: 'npx', env: { PORT: 5432 } } })).server.env_vars)
      .toEqual({ PORT: '5432' })
  })

  it('takes a bare server object, and infers the transport', () => {
    expect(parseMcpConfig('{"url": "https://x/sse", "type": "sse"}').server).toMatchObject({ name: '', transport: 'sse' })
    expect(parseMcpConfig('{"serverUrl": "https://x/mcp"}').server).toMatchObject({ transport: 'http', url: 'https://x/mcp' })
    expect(parseMcpConfig('{"command": "uvx", "args": ["mcp-server-git"]}').server.transport).toBe('stdio')
    expect(parseMcpConfig('{"url": "https://x/mcp", "type": "streamable-http"}').server.transport).toBe('http')
  })

  it('says what is wrong', () => {
    expect(() => parseMcpConfig('{nope')).toThrow(/Not valid JSON/)
    expect(() => parseMcpConfig('[]')).toThrow(/JSON object/)
    expect(() => parseMcpConfig('{"mcpServers": {}}')).toThrow(/No MCP server/)
    expect(() => parseMcpConfig('{"command": "x", "args": "a b"}')).toThrow(/"args" must be a list/)
    expect(() => parseMcpConfig('{"command": "x", "type": "ws"}')).toThrow(/Unknown transport/)
  })
})

describe('splitArgs / joinArgs', () => {
  it('keeps args with spaces together, round trip', () => {
    const args = ['-y', '@modelcontextprotocol/server-filesystem', '/Users/me/My Documents', '']
    expect(joinArgs(args)).toBe('-y @modelcontextprotocol/server-filesystem "/Users/me/My Documents" ""')
    expect(splitArgs(joinArgs(args))).toEqual(args)
    expect(splitArgs(`a 'b "c"' d`)).toEqual(['a', 'b "c"', 'd'])
  })
})
