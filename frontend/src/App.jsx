import { useState, useCallback } from 'react'
import ParametersPanel from './components/ParametersPanel'
import ResultPanel from './components/ResultPanel'
import { startAnalysis, openEventStream } from './api'

export default function App() {
  const [jobId, setJobId] = useState(null)
  const [status, setStatus] = useState('idle') // idle | running | done | error
  const [messages, setMessages] = useState([])
  const [startTime, setStartTime] = useState(null)
  const [resultCollapsed, setResultCollapsed] = useState(false)

  const handleSubmit = useCallback(async (params) => {
    // Reset state
    setMessages([])
    setStatus('running')
    setJobId(null)

    const t0 = Date.now()
    setStartTime(t0)

    let id
    try {
      const data = await startAnalysis(params)
      id = data.job_id
      setJobId(id)
    } catch (err) {
      setMessages([{ type: 'error', message: `Ошибка запуска: ${err.message}` }])
      setStatus('error')
      return
    }

    // Open SSE stream
    const es = openEventStream(id, (msg) => {
      setMessages((prev) => [...prev, msg])
      if (msg.type === 'done') {
        setStatus('done')
        es.close()
      } else if (msg.type === 'error') {
        setStatus('error')
        es.close()
      }
    })
  }, [])

  return (
    <div className="app-wrapper">
      <header className="app-header">
        <h1>Генератор синопсиса биоэквивалентности</h1>
        {/* <span className="subtitle">Генератор синопсиса протокола биоэквивалентности</span> */}
      </header>

      <div className="app-body">
        <ParametersPanel onSubmit={handleSubmit} isRunning={status === 'running'} />
        <ResultPanel
          status={status}
          messages={messages}
          jobId={jobId}
          startTime={startTime}
          collapsed={resultCollapsed}
          onToggleCollapse={() => setResultCollapsed(c => !c)}
        />
      </div>
    </div>
  )
}
