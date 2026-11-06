import { useEffect, useState } from 'react'

/**
 * How many columns a ``repeat(auto-fill, minmax(minWidth, 1fr))`` grid shows at its current width, so paged
 * lists can fill whole rows. Pass ``ref`` as the grid's ref (a callback ref, so a grid that mounts later — on
 * another tab — is measured too). ``fallback`` is used until it's measured, and in tests.
 */
export function useGridColumns<T extends HTMLElement>(minWidth: number, gap: number, fallback = 3) {
  const [el, ref] = useState<T | null>(null)
  const [columns, setColumns] = useState(fallback)

  useEffect(() => {
    if (!el || typeof ResizeObserver === 'undefined') return
    const measure = () => {
      const width = el.clientWidth
      if (width > 0) setColumns(Math.max(1, Math.floor((width + gap) / (minWidth + gap))))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [el, minWidth, gap])

  return { ref, columns }
}

/** A page size of about ``target`` items that is a whole number of rows. */
export function fullRowsPageSize(columns: number, target: number): number {
  const cols = Math.max(1, columns)
  return Math.ceil(target / cols) * cols
}
