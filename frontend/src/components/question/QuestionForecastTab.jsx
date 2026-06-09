import React, { useState, useEffect } from 'react'
import { ForecastTab } from '../CaseStudyView/ForecastTab'
import { usePipelineJobs } from '../../hooks/usePipelineJobs'
import { fetchQuestionSlotPreview } from '../../api/graphApi'
import axios from 'axios'
import './QuestionForecastTab.css'

const SLOTS   = ['early', 'mid', 'late']
const MODES   = ['container', 'knowledge_only', 'real_time']

/** Compact timeline bar showing where simulated date sits in the window. */
const SlotBar = ({ preview }) => {
  if (!preview) return null
  const start = new Date(preview.window_start)
  const end   = new Date(preview.window_end)
  const sim   = new Date(preview.simulated_date)
  const pct   = Math.round(((sim - start) / (end - start)) * 100)
  const fmt   = d => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' })
  return (
    <div className="qft-slot-bar-wrap">
      <div className="qft-slot-bar">
        <div className="qft-slot-fill" style={{ width: `${pct}%` }} />
        <div className="qft-slot-marker" style={{ left: `${pct}%` }} title={`Simulated: ${fmt(sim)}`} />
      </div>
      <div className="qft-slot-labels">
        <span>{fmt(start)}</span>
        <span className="qft-slot-sim">{fmt(sim)}</span>
        <span>{fmt(end)}</span>
      </div>
    </div>
  )
}

const QuestionForecastTab = ({ question }) => {
  const [runOpen, setRunOpen]       = useState(false)
  const [model, setModel]           = useState('')
  const [slot, setSlot]             = useState('mid')
  const [mode, setMode]             = useState('container')
  const [causal, setCausal]         = useState(false)
  const [slotPreview, setSlotPreview] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitMsg, setSubmitMsg]   = useState(null)

  const { loadJobs } = usePipelineJobs('forecast')

  // Fetch slot preview when slot changes and popover is open
  useEffect(() => {
    if (!runOpen || !question?.id) return
    fetchQuestionSlotPreview(question.id, slot)
      .then(setSlotPreview)
      .catch(() => setSlotPreview(null))
  }, [runOpen, question?.id, slot])

  const handleRun = async () => {
    if (!model.trim()) { setSubmitMsg('Enter a model name.'); return }
    setSubmitting(true)
    setSubmitMsg(null)
    try {
      await axios.post('/api/pipelines/jobs', {
        question_ids:    [question.id],
        pipeline_type:   'forecast',
        config: {
          model:               model.trim(),
          slot,
          mode,
          enable_causal_tools: causal,
        },
      })
      setSubmitMsg('Forecast job started.')
      loadJobs()
      setTimeout(() => { setRunOpen(false); setSubmitMsg(null) }, 1500)
    } catch (err) {
      setSubmitMsg(`Error: ${err.response?.data?.detail || err.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="qft">
      {/* Header row with subtle run button */}
      <div className="qft-header">
        <span className="qft-header-title">Forecast Results</span>
        <button
          className="qft-run-btn"
          onClick={() => setRunOpen(o => !o)}
          title="Run a new forecast for this question"
        >
          ▶ Run Forecast
        </button>
      </div>

      {/* Run popover */}
      {runOpen && (
        <div className="qft-popover">
          <div className="qft-popover-row">
            <label>Model</label>
            <input
              className="qft-input"
              placeholder="e.g. openai/gpt-4o"
              value={model}
              onChange={e => setModel(e.target.value)}
            />
          </div>
          <div className="qft-popover-row">
            <label>Slot</label>
            <div className="qft-btn-group">
              {SLOTS.map(s => (
                <button key={s} className={`qft-opt-btn ${slot === s ? 'active' : ''}`} onClick={() => setSlot(s)}>{s}</button>
              ))}
            </div>
          </div>
          <div className="qft-popover-row">
            <label>Mode</label>
            <div className="qft-btn-group">
              {MODES.map(m => (
                <button key={m} className={`qft-opt-btn ${mode === m ? 'active' : ''}`} onClick={() => setMode(m)}>
                  {m.replace('_', ' ')}
                </button>
              ))}
            </div>
          </div>
          <div className="qft-popover-row">
            <label>Causal tools</label>
            <button
              className={`qft-opt-btn ${causal ? 'active' : ''}`}
              onClick={() => setCausal(c => !c)}
            >
              {causal ? 'On' : 'Off'}
            </button>
          </div>
          {slotPreview && <SlotBar preview={slotPreview} />}
          {submitMsg && <div className="qft-submit-msg">{submitMsg}</div>}
          <div className="qft-popover-actions">
            <button className="qft-cancel-btn" onClick={() => setRunOpen(false)}>Cancel</button>
            <button className="qft-confirm-btn" onClick={handleRun} disabled={submitting}>
              {submitting ? 'Starting…' : 'Start'}
            </button>
          </div>
        </div>
      )}

      {/* Forecast list — reuse existing ForecastTab */}
      <div className="qft-list">
        <ForecastTab selectedQuestion={question} />
      </div>
    </div>
  )
}

export default QuestionForecastTab
