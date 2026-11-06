/**
 * Download a file from the API. Goes through fetch (not a plain <a href>) so the auth token and
 * tenant/project scope headers that TenantContext injects are sent — a bare link would be anonymous.
 */
export async function downloadFile(url: string, fallbackName: string): Promise<void> {
  const res = await fetch(url)
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : `Download failed (HTTP ${res.status})`)
  }
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const name = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? fallbackName
  saveBlob(await res.blob(), name)
}

/** Save a blob built in the browser as a file. */
export function saveBlob(blob: Blob, name: string): void {
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}

/** Click handler for a download button: reports failures instead of failing silently. */
export function onDownload(url: string, fallbackName: string) {
  return (e: { stopPropagation: () => void }) => {
    e.stopPropagation()
    downloadFile(url, fallbackName).catch((err) => window.alert(err instanceof Error ? err.message : String(err)))
  }
}
