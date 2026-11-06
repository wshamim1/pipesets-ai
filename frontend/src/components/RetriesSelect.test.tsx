import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RetriesSelect, attemptLabel, retriesField } from './RetriesSelect'

describe('RetriesSelect', () => {
  it('offers never, 1–10 and until it succeeds, plus the server default on create', () => {
    const onChange = vi.fn()
    render(<RetriesSelect value="" onChange={onChange} allowDefault />)
    const select = screen.getByLabelText(/Retry failed runs/) as HTMLSelectElement
    const values = Array.from(select.options).map((o) => o.value)
    expect(values).toEqual(['', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '-1'])
    fireEvent.change(select, { target: { value: '-1' } })
    expect(onChange).toHaveBeenCalledWith('-1')
  })

  it('has no server default when editing', () => {
    render(<RetriesSelect value="2" onChange={() => {}} allowDefault={false} />)
    const select = screen.getByLabelText(/Retry failed runs/) as HTMLSelectElement
    expect(select.options[0].value).toBe('0')
    expect(select.value).toBe('2')
  })

  it('maps picker values to the API field', () => {
    expect(retriesField('')).toBeUndefined()
    expect(retriesField('0')).toBe(0)
    expect(retriesField('-1')).toBe(-1)
  })

  it('labels runs that took more than one attempt', () => {
    expect(attemptLabel(1, 2)).toBe('')
    expect(attemptLabel(2, 2)).toBe('attempt 2 of 3')
    expect(attemptLabel(7, -1)).toBe('attempt 7')
  })
})
