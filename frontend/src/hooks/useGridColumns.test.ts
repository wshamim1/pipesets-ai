import { describe, expect, it } from 'vitest'
import { fullRowsPageSize } from './useGridColumns'

describe('fullRowsPageSize', () => {
  it('rounds about 12 items up to whole rows', () => {
    expect([1, 2, 3, 4, 5, 6, 7, 8].map((c) => fullRowsPageSize(c, 12))).toEqual([12, 12, 12, 12, 15, 12, 14, 16])
    expect(fullRowsPageSize(0, 12)).toBe(12)
  })
})
