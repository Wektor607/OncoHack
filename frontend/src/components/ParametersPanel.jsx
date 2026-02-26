import { useState } from 'react'

const DOSAGE_FORMS = ['tablet', 'capsule', 'solution', 'suspension', 'powder',
  'injection', 'cream', 'ointment', 'patch', 'spray', 'drops', 'other']

const UNITS = ['mg', 'g', 'mcg', 'ug', 'ng', 'IU', 'mL']

const FED_STATES = [
  { value: 'натощак', label: 'Натощак' },
  { value: 'после приема высококалорийной пищи', label: 'После высококалорийной пищи' },
  { value: 'оба варианта', label: 'Оба варианта' },
]

const DESIGNS = [
  { value: 'auto', label: 'Авто (LLM выберет)' },
  { value: 'crossover_2x2', label: '2×2 Cross-over' },
  { value: 'replicate_partial', label: '3-way Replicate' },
  { value: 'replicate_full', label: '4-way Replicate' },
  { value: 'parallel', label: 'Параллельный' },
]

const ISV_OPTIONS = [
  { value: 'auto', label: 'Авто' },
  { value: 'low', label: 'Низкая (<30%)' },
  { value: 'high', label: 'Высокая (≥30%)' },
  { value: 'unknown', label: 'Неизвестна' },
]

export default function ParametersPanel({ onSubmit, isRunning }) {
  const [form, setForm] = useState({
    drug: '',
    form: '',
    strength: '',
    strength_unit: 'mg',
    dosing: 'однократный',
    dose_number: '',
    dose_unit: 'mg',
    fed_state: 'натощак',
    max_pubmed: 10,
    max_fda: 10,
    // advanced
    isv: 'auto',
    isv_cv: '',
    rsabe: 'auto',
    design: 'auto',
    design_notes: '',
    sex: 'any',
    age_min: '',
    age_max: '',
  })

  const [showAdvanced, setShowAdvanced] = useState(false)

  const set = (field) => (e) =>
    setForm((prev) => ({ ...prev, [field]: e.target.value }))

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!form.drug.trim()) return

    const params = {
      drug: form.drug.trim(),
      form: form.form || null,
      strength: form.strength ? parseFloat(form.strength) : null,
      strength_unit: form.strength_unit,
      dosing: form.dosing,
      dose_number: form.dose_number ? parseFloat(form.dose_number) : null,
      dose_unit: form.dose_unit,
      fed_state: form.fed_state,
      max_pubmed: parseInt(form.max_pubmed, 10) || 10,
      max_fda: parseInt(form.max_fda, 10) || 3,
      isv: form.isv,
      isv_cv: form.isv_cv ? parseFloat(form.isv_cv) : null,
      rsabe: form.rsabe,
      design: form.design,
      design_notes: form.design_notes || null,
      sex: form.sex,
      age_min: form.age_min ? parseInt(form.age_min, 10) : null,
      age_max: form.age_max ? parseInt(form.age_max, 10) : null,
    }
    onSubmit(params)
  }

  return (
    <aside className="left-panel">
      <p className="form-section-title">Параметры анализа</p>

      <form onSubmit={handleSubmit}>
        {/* Drug INN */}
        <div className="form-group">
          <label className="form-label">
            ИНН препарата <span className="required">*</span>
          </label>
          <input
            className="form-input"
            placeholder="amlodipine, metformin…"
            value={form.drug}
            onChange={set('drug')}
            required
          />
        </div>

        {/* Dosage form */}
        <div className="form-group">
          <label className="form-label">Форма выпуска</label>
          <select className="form-select" value={form.form} onChange={set('form')}>
            <option value="">— не указана —</option>
            {DOSAGE_FORMS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>

        {/* Strength */}
        <div className="form-group">
          <label className="form-label">Дозировка</label>
          <div className="form-row">
            <input
              className="form-input"
              type="number"
              min="0"
              step="any"
              placeholder="5"
              value={form.strength}
              onChange={set('strength')}
            />
            <select className="form-select" style={{ maxWidth: 80 }} value={form.strength_unit} onChange={set('strength_unit')}>
              {UNITS.map((u) => <option key={u}>{u}</option>)}
            </select>
          </div>
        </div>

        {/* Dosing regime */}
        <div className="form-group">
          <label className="form-label">Режим дозирования</label>
          <select className="form-select" value={form.dosing} onChange={set('dosing')}>
            <option value="однократный">Однократный</option>
            <option value="многократный">Многократный</option>
          </select>
        </div>

        {/* Fed state */}
        <div className="form-group">
          <label className="form-label">Режим приёма пищи</label>
          <select className="form-select" value={form.fed_state} onChange={set('fed_state')}>
            {FED_STATES.map(({ value, label }) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>

        {/* Source limits */}
        <div className="form-group">
          <label className="form-label">Источники данных (макс. записей)</label>
          <div className="form-row">
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>PubMed</div>
              <input
                className="form-input"
                type="number"
                min="1"
                value={form.max_pubmed}
                onChange={set('max_pubmed')}
              />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>OpenFDA</div>
              <input
                className="form-input"
                type="number"
                min="0"
                value={form.max_fda}
                onChange={set('max_fda')}
              />
            </div>
          </div>
        </div>

        {/* Advanced toggle */}
        <button
          type="button"
          className="advanced-toggle"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          <span>{showAdvanced ? '▾' : '▸'}</span>
          Дополнительные параметры
        </button>

        {showAdvanced && (
          <div className="advanced-section">
            {/* Dose */}
            <div className="form-group">
              <label className="form-label">Разовая доза</label>
              <div className="form-row">
                <input
                  className="form-input"
                  type="number"
                  min="0"
                  step="any"
                  placeholder="10"
                  value={form.dose_number}
                  onChange={set('dose_number')}
                />
                <select className="form-select" style={{ maxWidth: 80 }} value={form.dose_unit} onChange={set('dose_unit')}>
                  {UNITS.map((u) => <option key={u}>{u}</option>)}
                </select>
              </div>
            </div>

            {/* ISV */}
            <div className="form-group">
              <label className="form-label">Внутрисубъектная вариабельность (ISV)</label>
              <select className="form-select" value={form.isv} onChange={set('isv')}>
                {ISV_OPTIONS.map(({ value, label }) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>

            {/* ISV CV */}
            <div className="form-group">
              <label className="form-label">CVintra, % (если известен)</label>
              <input
                className="form-input"
                type="number"
                min="0"
                max="100"
                step="0.1"
                placeholder="25.0"
                value={form.isv_cv}
                onChange={set('isv_cv')}
              />
            </div>

            {/* Design preference */}
            <div className="form-group">
              <label className="form-label">Предпочтительный дизайн</label>
              <select className="form-select" value={form.design} onChange={set('design')}>
                {DESIGNS.map(({ value, label }) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>

            {/* RSABE */}
            <div className="form-group">
              <label className="form-label">RSABE</label>
              <select className="form-select" value={form.rsabe} onChange={set('rsabe')}>
                <option value="auto">Авто</option>
                <option value="yes">Да</option>
                <option value="no">Нет</option>
              </select>
            </div>

            {/* Sex */}
            <div className="form-group">
              <label className="form-label">Гендерный состав</label>
              <select className="form-select" value={form.sex} onChange={set('sex')}>
                <option value="any">Любой</option>
                <option value="male_only">Только мужчины</option>
                <option value="female_only">Только женщины</option>
                <option value="mixed">Смешанный</option>
              </select>
            </div>

            {/* Age range */}
            <div className="form-group">
              <label className="form-label">Возраст участников</label>
              <div className="form-row">
                <input
                  className="form-input"
                  type="number"
                  min="0"
                  placeholder="от"
                  value={form.age_min}
                  onChange={set('age_min')}
                />
                <input
                  className="form-input"
                  type="number"
                  min="0"
                  placeholder="до"
                  value={form.age_max}
                  onChange={set('age_max')}
                />
              </div>
            </div>
          </div>
        )}

        <button type="submit" className="btn-submit" disabled={isRunning}>
          {isRunning ? '⟳ Анализ...' : '▶ Анализировать'}
        </button>
      </form>
    </aside>
  )
}
