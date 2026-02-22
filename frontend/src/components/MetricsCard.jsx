import { useEffect, useState } from 'react'
import { getMetrics } from '../api'

function Chip({ label, value, sub, highlight }) {
  return (
    <div className="metric-chip">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${highlight ? 'highlight' : ''}`}>{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  )
}

export default function MetricsCard({ jobId }) {
  const [metrics, setMetrics] = useState(null)

  useEffect(() => {
    if (!jobId) return
    getMetrics(jobId).then(setMetrics).catch(console.error)
  }, [jobId])

  if (!metrics) return null

  const consistencyLabel = metrics.sources_consistency != null
    ? `SD = ${metrics.sources_consistency}%`
    : metrics.sources_count > 1 ? 'Нет данных' : '1 источник'

  return (
    <div className="metrics-bar">
      <Chip
        label="Источников"
        value={metrics.sources_count}
        sub="найдено"
        highlight
      />
      <Chip
        label="Покрытие данных"
        value={`${metrics.data_coverage}%`}
        sub="ключевых PK-параметров"
      />
      <Chip
        label="CVintra"
        value={metrics.cv_intra != null ? `${metrics.cv_intra}%` : '—'}
        sub={metrics.cv_reliability}
      />
      <Chip
        label="Согласованность"
        value={consistencyLabel}
        sub="разброс CVintra"
      />
      <Chip
        label="Время генерации"
        value={`${metrics.generation_time}с`}
        sub={`${metrics.design} / n=${metrics.n_subjects}`}
      />
    </div>
  )
}
