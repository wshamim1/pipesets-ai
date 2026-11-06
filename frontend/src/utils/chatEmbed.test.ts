/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { bubbleSnippet, embedUrl, iframeSnippet, samplePage } from './chatEmbed'

const URL_ = 'https://chat.example.com/c/pc_abc'

describe('chat embed snippets', () => {
  it('points at the chat page in embed mode', () => {
    expect(embedUrl(URL_)).toBe(`${URL_}?embed=1`)
    expect(embedUrl(`${URL_}?x=1`)).toBe(`${URL_}?x=1&embed=1`)
    expect(iframeSnippet(URL_, 'Help')).toContain(`src="${URL_}?embed=1"`)
  })

  it('loads the chat button lazily and escapes the title', () => {
    const html = bubbleSnippet(URL_, 'Tom & "Jerry" <b>')
    expect(html).toContain(`data-src="${URL_}?embed=1"`)
    expect(html).not.toMatch(/<iframe[^>]* src=/)
    expect(html).toContain('Tom &amp; &quot;Jerry&quot; &lt;b&gt;')
  })

  it('matches the example page in examples/chat-embed', () => {
    // vitest runs from frontend/
    const example = readFileSync(resolve(process.cwd(), '../examples/chat-embed/index.html'), 'utf8')
    expect(example).toBe(samplePage('https://YOUR-PUBLIC-HOST/c/pc_YOUR_LINK_TOKEN', 'Support assistant'))
  })
})
