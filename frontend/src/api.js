// API client for the FastAPI backend
// In dev mode, Vite proxies /api/* to localhost:8000
// In production, nginx proxies /api/* to backend container

export async function startAnalysis(params) {
  const res = await fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to start analysis')
  }
  return res.json()  // { job_id }
}

/**
 * Opens an SSE connection that calls onMessage(event) for each received event.
 * Returns the EventSource so the caller can call .close() on it.
 */
export function openEventStream(jobId, onMessage) {
  const es = new EventSource(`/api/stream/${jobId}`)
  es.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data))
    } catch {
      // ignore malformed events
    }
  }
  es.onerror = () => {
    // EventSource auto-reconnects; close only when we get a "done" or "error" msg
    es.close()
  }
  return es
}

export function getPreviewUrl(jobId) {
  return `/api/preview/${jobId}`
}

export function getDownloadUrl(jobId) {
  return `/api/download/${jobId}`
}

export async function getMetrics(jobId) {
  const res = await fetch(`/api/metrics/${jobId}`)
  if (!res.ok) throw new Error('Failed to fetch metrics')
  return res.json()
}
