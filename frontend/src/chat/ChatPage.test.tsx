import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatPage } from './ChatPage'
import { parseSse, tokenFromPath } from './chatApi'

const SESSION = {
  session: 'sess-1', resumed: false, title: 'Help desk', greeting: 'Hi! Ask me anything.', max_message_chars: 50,
  starter_prompts: [] as string[], about: null,
}

const ABOUT = {
  pipeline_id: 'app_123', version: 3,
  description: 'Answers weather questions.', models: ['gpt-4o (OpenAI)'], tools: ['Weather'],
  mcp_servers: ['Database Query (SQL)'], agents: [], pipelines: [], answers_from_documents: false,
}

function sse(...events: object[]): Response {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

const json = (status: number, body: object) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('chatApi', () => {
  it('reads the token from a /c/<token> path', () => {
    expect(tokenFromPath('/c/pc_abc-123_X')).toBe('pc_abc-123_X')
    expect(tokenFromPath('/c/pc_abc/')).toBe('pc_abc')
    expect(tokenFromPath('/c/')).toBeNull()
    expect(tokenFromPath('/c/a/b')).toBeNull()
    expect(tokenFromPath('/')).toBeNull()
  })

  it('splits SSE into events and keeps an unfinished one for later', () => {
    const { events, rest } = parseSse('data: {"type":"token","text":"Hel"}\n\ndata: {"type":"tok')
    expect(events).toEqual([{ type: 'token', text: 'Hel' }])
    expect(rest).toBe('data: {"type":"tok')
    expect(parseSse('data: not json\n\n').events).toEqual([])
  })
})

describe('ChatPage', () => {
  beforeEach(() => localStorage.clear())

  it('greets, streams an answer and remembers the conversation on this device', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(200, SESSION))
      .mockResolvedValueOnce(sse({ type: 'token', text: 'We open ' }, { type: 'token', text: 'at **9**.' }, { type: 'done' }))
    vi.stubGlobal('fetch', fetchMock)
    render(<ChatPage token="pc_t" />)

    expect(await screen.findByText('Hi! Ask me anything.')).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Help desk' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'When do you open?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('9')).toBeTruthy()
    expect(screen.getByText('When do you open?')).toBeTruthy()
    const [url, init] = fetchMock.mock.calls[1]
    expect(url).toMatch(/\/v1\/chat\/pc_t\/message$/)
    expect(JSON.parse(init.body)).toEqual({ session: 'sess-1', message: 'When do you open?' })
    await waitFor(() => expect(JSON.parse(localStorage.getItem('pipesets-chat:pc_t')!).messages).toHaveLength(2))
  })

  it('lets the visitor rate an answer with the token from its done event', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(200, SESSION))
      .mockResolvedValueOnce(sse({ type: 'token', text: 'Rent is due monthly.' }, { type: 'done', feedback: 'fb-sealed' }))
      .mockResolvedValueOnce(json(200, { ok: true, rating: -1 }))
      .mockResolvedValueOnce(json(200, { ok: true, rating: -1 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<ChatPage token="pc_t" />)
    await screen.findByText('Hi! Ask me anything.')
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Rent?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    fireEvent.click(await screen.findByRole('button', { name: 'Bad answer' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    const [url, init] = fetchMock.mock.calls[2]
    expect(url).toMatch(/\/v1\/chat\/pc_t\/feedback$/)
    expect(JSON.parse(init.body)).toEqual({ session: 'sess-1', feedback: 'fb-sealed', rating: -1, comment: '' })
    expect(screen.getByRole('button', { name: 'Bad answer' }).getAttribute('aria-pressed')).toBe('true')

    // After a 👎 it asks what was wrong
    fireEvent.change(screen.getByLabelText('What was wrong'), { target: { value: 'no amount' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send note' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
    expect(JSON.parse(fetchMock.mock.calls[3][1].body).comment).toBe('no amount')
    expect(await screen.findByText('Thanks for the feedback')).toBeTruthy()
  })

  it('continues a saved session after a reload', async () => {
    localStorage.setItem('pipesets-chat:pc_t', JSON.stringify({
      session: 'sess-1', messages: [{ role: 'user', content: 'Earlier question' }, { role: 'assistant', content: 'Earlier answer' }],
    }))
    const fetchMock = vi.fn().mockResolvedValueOnce(json(200, { ...SESSION, resumed: true }))
    vi.stubGlobal('fetch', fetchMock)
    render(<ChatPage token="pc_t" />)

    expect(await screen.findByText('Earlier answer')).toBeTruthy()
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ session: 'sess-1' })
  })

  it('shows limits and errors in plain words', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(json(200, SESSION))
      .mockResolvedValueOnce(json(429, { detail: 'Too many messages — wait a moment and try again' })))
    render(<ChatPage token="pc_t" />)
    const box = await screen.findByLabelText('Message')

    fireEvent.change(box, { target: { value: 'x'.repeat(51) } })
    expect(screen.getByText(/up to 50 characters/)).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true)

    fireEvent.change(box, { target: { value: 'hello' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('Too many messages — wait a moment and try again')).toBeTruthy()
  })

  it('shows the pipeline details and starts a chat from a sample prompt', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(200, { ...SESSION, about: ABOUT, starter_prompts: ['Weather in Oslo?', 'Forecast for Paris?'] }))
      .mockResolvedValueOnce(sse({ type: 'token', text: 'Sunny.' }, { type: 'done' }))
    vi.stubGlobal('fetch', fetchMock)
    render(<ChatPage token="pc_t" />)

    expect(await screen.findByText('Answers weather questions.')).toBeTruthy()
    expect(screen.getByText('gpt-4o (OpenAI)')).toBeTruthy()
    expect(screen.getByText('Weather')).toBeTruthy()
    expect(screen.getByText('Database Query (SQL)')).toBeTruthy()
    expect(screen.queryByText('Agents')).toBeNull()

    // ID, version and the builder link sit in a collapsed section
    const info = screen.getByText('Pipeline info').closest('details')!
    expect(info.open).toBe(false)
    expect(screen.getByText('app_123')).toBeTruthy()
    expect(screen.getByText('v3 (published)')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Open in Pipesets/ }).getAttribute('href')).toMatch(/\/\?pipeline=app_123$/)

    fireEvent.click(screen.getByRole('button', { name: 'Weather in Oslo?' }))
    expect(await screen.findByText('Sunny.')).toBeTruthy()
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).message).toBe('Weather in Oslo?')
    // Once chatting, prompts and details step aside; About brings the details back
    expect(screen.queryByRole('button', { name: 'Forecast for Paris?' })).toBeNull()
    expect(screen.queryByText('Answers weather questions.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'About' }))
    expect(screen.getByText('Answers weather questions.')).toBeTruthy()
  })

  it('reads JSON answers: a lone error as its message, anything else formatted', async () => {
    localStorage.setItem('pipesets-chat:pc_t', JSON.stringify({ session: 'sess-1', messages: [
      { role: 'user', content: 'Weather in Allentown?' },
      { role: 'assistant', content: '{"error":"City not found: \'Allentown, USA\'."}' },
      { role: 'user', content: 'And Paris?' },
      { role: 'assistant', content: '{"city":"Paris","temp_c":18}' },
    ] }))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(200, { ...SESSION, resumed: true })))
    render(<ChatPage token="pc_t" />)

    expect(await screen.findByText("City not found: 'Allentown, USA'.")).toBeTruthy()
    expect(screen.queryByText(/"error"/)).toBeNull()
    expect(screen.getByText(/"temp_c": 18/)).toBeTruthy()
  })

  it('says when a link is turned off', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(json(404, { detail: "This chat link doesn't exist or has been turned off" })))
    render(<ChatPage token="pc_gone" />)
    expect(await screen.findByText('Chat unavailable')).toBeTruthy()
    expect(screen.getByText(/turned off/)).toBeTruthy()
  })
})
