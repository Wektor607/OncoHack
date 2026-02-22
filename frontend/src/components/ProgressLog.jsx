import { useEffect, useRef, useState } from 'react'

function formatTime(seconds) {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

const STEP_ICONS = {
  init:       '🔍',
  extraction: '📚',
  llm:        '🤖',
  docx:       '📄',
}

function LogIcon({ msg }) {
  if (msg.type === 'step') {
    return <span className="log-icon spinning">⚙</span>
  }
  if (msg.type === 'done') return <span className="log-icon">✅</span>
  if (msg.type === 'error') return <span className="log-icon">❌</span>
  return <span className="log-icon" style={{ opacity: .5 }}>›</span>
}

export default function ProgressLog({ messages, startTime, status }) {
  // Инициализируем с реальным временем — важно при ремонтировании в статусе done/error
  const [elapsed, setElapsed] = useState(() =>
    startTime ? (Date.now() - startTime) / 1000 : 0
  )
  const bottomRef = useRef(null)

  // Timer — stops automatically when status becomes done/error
  useEffect(() => {
    if (!startTime) return
    if (status === 'done' || status === 'error') return  // freeze, don't restart
    const id = setInterval(() => {
      setElapsed((Date.now() - startTime) / 1000)
    }, 200)
    return () => clearInterval(id)  // cleanup clears interval on status change
  }, [startTime, status])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const lastStep = messages.filter((m) => m.type === 'step').at(-1)

  return (
    <div className="progress-container">
      <div className="progress-header">
        <div>
          <div className="progress-title">
            {status === 'running' ? '⟳ Выполняется анализ...' : ''}
            {status === 'done'    ? '✅ Анализ завершён'     : ''}
            {status === 'error'   ? '❌ Ошибка выполнения'   : ''}
          </div>
          {lastStep && status === 'running' && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              {STEP_ICONS[lastStep.step] || '⚙'} {lastStep.message}
            </div>
          )}
        </div>
        <div className="timer">{formatTime(elapsed)}</div>
      </div>

      <div className="log-list">
        {messages.map((msg, i) => (
          <div key={i} className={`log-item ${msg.type}`}>
            <LogIcon msg={msg} />
            <span>{msg.message}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
