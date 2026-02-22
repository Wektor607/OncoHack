import ProgressLog from './ProgressLog'
import DocPreview from './DocPreview'
import MetricsCard from './MetricsCard'

export default function ResultPanel({ status, messages, jobId, startTime }) {
  // ── Idle ─────────────────────────────────────────────────────────────────────
  if (status === 'idle') {
    return (
      <main className="right-panel">
        <div className="idle-placeholder">
          <div className="icon">🧬</div>
          <p>
            Введите МНН препарата в левой панели и нажмите{' '}
            <strong>Анализировать</strong>.<br />
            Система найдёт фармакокинетические данные и сгенерирует синопсис протокола
            биоэквивалентности в формате Word.
          </p>
        </div>
      </main>
    )
  }

  // ── Running ───────────────────────────────────────────────────────────────────
  if (status === 'running') {
    return (
      <main className="right-panel">
        <ProgressLog messages={messages} startTime={startTime} status={status} />
      </main>
    )
  }

  // ── Error ─────────────────────────────────────────────────────────────────────
  if (status === 'error') {
    return (
      <main className="right-panel">
        <ProgressLog messages={messages} startTime={startTime} status={status} />
      </main>
    )
  }

  // ── Done ──────────────────────────────────────────────────────────────────────
  return (
    <main className="right-panel" style={{ overflow: 'hidden' }}>
      {/* Compact progress summary at top */}
      <div style={{ maxHeight: 140, overflowY: 'auto', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <ProgressLog messages={messages} startTime={startTime} status={status} />
      </div>

      {/* Metrics row */}
      <MetricsCard jobId={jobId} />

      {/* Document preview + download */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <DocPreview jobId={jobId} />
      </div>
    </main>
  )
}
