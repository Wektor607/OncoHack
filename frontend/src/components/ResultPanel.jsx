import { useState, useRef, useCallback } from 'react'
import ProgressLog from './ProgressLog'
import DocPreview from './DocPreview'
import MetricsCard from './MetricsCard'

export default function ResultPanel({ status, messages, jobId, startTime, collapsed, onToggleCollapse }) {
  const [topHeight, setTopHeight] = useState(260)
  const startY = useRef(0)
  const startH = useRef(0)

  const onDragStart = useCallback((e) => {
    startY.current = e.clientY
    startH.current = topHeight

    const onMove = (e) => {
      const delta = e.clientY - startY.current
      setTopHeight(Math.max(60, Math.min(520, startH.current + delta)))
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [topHeight])

  const toggleBtn = (
    <button
      className="panel-collapse-btn"
      onClick={onToggleCollapse}
      title={collapsed ? 'Развернуть панель результатов' : 'Свернуть панель результатов'}
    >
      {collapsed ? '▶' : '◀'}
    </button>
  )

  if (collapsed) {
    return (
      <aside className="right-panel right-panel--collapsed">
        {toggleBtn}
      </aside>
    )
  }

  // ── Idle ─────────────────────────────────────────────────────────────────────
  if (status === 'idle') {
    return (
      <main className="right-panel">
        {toggleBtn}
        <div className="idle-placeholder">
          <div className="icon">🧬</div>
          <p>
            Введите ИНН препарата в левой панели и нажмите{' '}
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
        {toggleBtn}
        <ProgressLog messages={messages} startTime={startTime} status={status} />
      </main>
    )
  }

  // ── Error ─────────────────────────────────────────────────────────────────────
  if (status === 'error') {
    return (
      <main className="right-panel">
        {toggleBtn}
        <ProgressLog messages={messages} startTime={startTime} status={status} />
      </main>
    )
  }

  // ── Done ──────────────────────────────────────────────────────────────────────
  return (
    <main className="right-panel" style={{ overflow: 'hidden' }}>
      {toggleBtn}

      {/* Top section — height controlled by drag handle */}
      <div style={{ height: topHeight, flexShrink: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, overflowY: 'auto', borderBottom: '1px solid var(--border)', minHeight: 0 }}>
          <ProgressLog messages={messages} startTime={startTime} status={status} />
        </div>
        <MetricsCard jobId={jobId} />
      </div>

      {/* Drag handle */}
      <div className="resize-handle" onMouseDown={onDragStart} title="Потяните чтобы изменить размер" />

      {/* Document preview + download */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <DocPreview jobId={jobId} />
      </div>
    </main>
  )
}
