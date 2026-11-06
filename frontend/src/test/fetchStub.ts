import { vi } from 'vitest'

type Route = (init: RequestInit | undefined, url: string) => unknown

/** A JSON response; `status` ≥ 400 makes `ok` false. */
export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/**
 * Stubs `fetch` with routes keyed by "METHOD /path" (path after API_BASE). A route returns a
 * Response, or any other value to send it as JSON. A `'*'` route answers anything unmatched;
 * without one, unmatched requests reject, like a backend that isn't running. Returns the mock,
 * so tests can inspect its calls.
 */
export function stubFetch(routes: Record<string, Route | unknown>) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const key = `${init?.method ?? 'GET'} ${new URL(url).pathname}`
    const route = key in routes ? routes[key] : routes['*']
    if (route === undefined) throw new TypeError(`Failed to fetch: ${key}`)
    const out = typeof route === 'function' ? (route as Route)(init, url) : route
    return out instanceof Response ? out : json(out)
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

/** The parsed JSON body of the n-th call to `fetch` matching `key` ("METHOD /path"). */
export function sentBody(mock: ReturnType<typeof stubFetch>, key: string, n = 0) {
  const calls = mock.mock.calls.filter(([input, init]) =>
    `${init?.method ?? 'GET'} ${new URL(String(input)).pathname}` === key)
  return JSON.parse(String(calls[n]?.[1]?.body))
}
