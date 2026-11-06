import { describe, expect, it } from 'vitest'
import { guessCaseColumns, rowHeaders, rowsToFile } from './syntheticExport'

const rows = [{ q: 'Hi, "you"', n: 1 }, { q: 'line\nbreak', extra: { a: 1 } }]

describe('rowsToFile', () => {
  it('writes CSV with every column and quoted cells', () => {
    const f = rowsToFile(rows, 'csv', 'my data')
    expect(f.filename).toBe('my_data.csv')
    expect(f.content).toBe('q,n,extra\r\n"Hi, ""you""",1,\r\n"line\nbreak",,"{""a"":1}"\r\n')
  })
  it('writes JSONL and JSON', () => {
    expect(rowsToFile(rows, 'jsonl', 'd').content.trim().split('\n').map((l) => JSON.parse(l))).toEqual(rows)
    expect(JSON.parse(rowsToFile(rows, 'json', 'd').content)).toEqual(rows)
  })
})

describe('column helpers', () => {
  it('collects headers in first-seen order', () => {
    expect(rowHeaders(rows)).toEqual(['q', 'n', 'extra'])
  })
  it('guesses prompt and expected columns', () => {
    expect(guessCaseColumns(['id', 'Question', 'answer'])).toEqual({ prompt: 'Question', expected: 'answer' })
    expect(guessCaseColumns(['id', 'age'])).toEqual({ prompt: '', expected: '' })
  })
})
