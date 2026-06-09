import React, { useState, useEffect, useCallback } from 'react'
import { fetchBenchmarkResults, fetchBenchmarkResult, fetchBenchmarkResultFiltered } from '../../api/graphApi'
import axios from 'axios'
import './BenchmarkMatrix.css'

const API_BASE = '/api'

async function fetchReasoningEval() {
  const res = await axios.get(`${API_BASE}/benchmark/reasoning-eval`)
  return res.data
}

// ── Metric definitions ────────────────────────────────────────────────────────
const METRICS = [
  { key: 'accuracy',              label: 'Accuracy',          fmt: v => v != null ? `${(v*100).toFixed(1)}%` : '—', higher: true,  src: 'autobench' },
  { key: 'brier',                 label: 'Brier',             fmt: v => v != null ? v.toFixed(3)              : '—', higher: false, src: 'autobench' },
  { key: 'log_score',             label: 'Log Score',         fmt: v => v != null ? v.toFixed(3)              : '—', higher: true,  src: 'reasoning' },
  { key: 'exact_source_precision',label: 'Src Precision',     fmt: v => v != null ? `${(v*100).toFixed(1)}%` : '—', higher: true,  src: 'reasoning' },
  { key: 'event_f1',              label: 'Event F1',          fmt: v => v != null ? `${(v*100).toFixed(1)}%` : '—', higher: true,  src: 'reasoning' },
  { key: 'key_event_recall',      label: 'KE Recall',         fmt: v => v != null ? `${(v*100).toFixed(1)}%` : '—', higher: true,  src: 'reasoning' },
  { key: 'key_event_precision',   label: 'KE Precision',      fmt: v => v != null ? `${(v*100).toFixed(1)}%` : '—', higher: true,  src: 'reasoning' },
  { key: 'accessible_event_f1',   label: 'Acc. Event F1',     fmt: v => v != null ? `${(v*100).toFixed(1)}%` : '—', higher: true,  src: 'reasoning' },
  { key: 'temporal_mae_days',     label: 'Temporal MAE',      fmt: v => v != null ? `${v.toFixed(0)}d`       : '—', higher: false, src: 'reasoning' },
]

// ── Paper condition display names ─────────────────────────────────────────────
const COND_LABELS = {
  vanilla_llm:          'Vanilla LLM',
  structured_scenario:  'Causal Simulation',
  search_enabled:       'Search-Enabled',
  worldreasoner:        'Search-Enabled Graph',
  oracle:               'Near-Resolution',
  real_time:            'Real-Time',
}

function condLabel(cond) {
  return COND_LABELS[cond] || cond.replace(/_/g, ' ')
}

/**
 * Build condition×model map using the LATEST run for each (condition, model) cell.
 * Runs are sorted newest-first so the first match wins — no double-counting across runs.
 */
function aggregateRuns(runs, runDetails) {
  const sortedRunIds = [...runs]
    .sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0))
    .map(r => r.run_id)

  const latest = {}
  for (const runId of sortedRunIds) {
    const detail = runDetails[runId]
    if (!detail) continue
    for (const [cond, modelMap] of Object.entries(detail.condition_results || {})) {
      if (!latest[cond]) latest[cond] = {}
      for (const [model, result] of Object.entries(modelMap)) {
        if (!latest[cond][model]) latest[cond][model] = { ...result, runId }
      }
    }
  }

  const matrix = {}
  for (const [cond, modelMap] of Object.entries(latest)) {
    matrix[cond] = {}
    for (const [model, result] of Object.entries(modelMap)) {
      const n = result.successful || 0
      matrix[cond][model] = {
        accuracy: result.accuracy ?? null,
        brier:    result.avg_brier_score ?? null,
        n,
        runId: result.runId,
      }
    }
  }
  return matrix
}

/** Merge reasoning-eval metrics into matrix cells (keyed by condition::model). */
function mergeReasoningMetrics(matrix, reasoningData) {
  if (!reasoningData?.by_condition_model) return matrix
  const bycm = reasoningData.by_condition_model
  const merged = {}
  for (const [cond, modelMap] of Object.entries(matrix)) {
    merged[cond] = {}
    for (const [model, cell] of Object.entries(modelMap)) {
      const rKey = `${cond}::${model}`
      const rStats = bycm[rKey] || {}
      merged[cond][model] = { ...cell, ...rStats }
    }
  }
  return merged
}

// ── Component ─────────────────────────────────────────────────────────────────
const BenchmarkMatrix = ({ onRefresh }) => {
  const [runs, setRuns]             = useState([])
  const [runDetails, setRunDetails] = useState({})
  const [reasoning, setReasoning]   = useState(null)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState(null)
  const [expanded, setExpanded]     = useState(null)
  const [metric, setMetric]         = useState('accuracy')
  const [contamFilter, setContamFilter] = useState(true)
  const [evaluating, setEvaluating] = useState(false)

  const load = useCallback(async (withFilter = true) => {
    setLoading(true)
    setError(null)
    try {
      const [list, reasoningData] = await Promise.all([
        fetchBenchmarkResults(),
        fetchReasoningEval().catch(() => null),
      ])
      setRuns(list)
      setReasoning(reasoningData)

      const fetcher = withFilter ? fetchBenchmarkResultFiltered : fetchBenchmarkResult
      const details = await Promise.all(
        list.map(r => fetcher(r.run_id).catch(() =>
          fetchBenchmarkResult(r.run_id).catch(() => null)
        ))
      )
      const map = {}
      list.forEach((r, i) => { if (details[i]) map[r.run_id] = details[i] })
      setRunDetails(map)
    } catch (err) {
      console.error('Error loading benchmark results:', err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const runReasoningEval = useCallback(async () => {
    setEvaluating(true)
    try {
      await axios.post(`${API_BASE}/pipelines/jobs`, {
        pipeline_type: 'reasoning_eval',
        config: {
          include_ids: 'include_ids.txt',
          filter_knowledge_leakage: true,
          exclude_annotation_rejected: true,
          match_method: 'hybrid',
        },
      })
      // Reload after a short delay so the new eval file is picked up
      setTimeout(() => { load(contamFilter); setEvaluating(false) }, 3000)
    } catch (err) {
      console.error('Failed to start reasoning eval:', err)
      setEvaluating(false)
    }
  }, [contamFilter, load])

  const toggleContamFilter = useCallback((val) => {
    setContamFilter(val)
    load(val)
  }, [load])

  useEffect(() => { load(true) }, [load])

  if (loading) return <div className="bm-state">Loading results…</div>
  if (error)   return <div className="bm-state error">{error}</div>
  if (runs.length === 0) return (
    <div className="bm-state muted">No benchmark results yet.</div>
  )

  const baseMatrix = aggregateRuns(runs, runDetails)
  const matrix     = mergeReasoningMetrics(baseMatrix, reasoning)
  const conditions = Object.keys(matrix).sort()
  const models = [...new Set(
    Object.values(matrix).flatMap(m => Object.keys(m))
  )].sort()

  if (conditions.length === 0)
    return <div className="bm-state muted">Results loaded but no condition data found.</div>

  const toggleExpand = (cond, model) => {
    const key = `${cond}:${model}`
    setExpanded(prev => prev === key ? null : key)
  }

  const metricDef = METRICS.find(m => m.key === metric) || METRICS[0]

  // Best per condition for highlight
  const bestPerCond = {}
  for (const cond of conditions) {
    let best = metricDef.higher ? -Infinity : Infinity
    for (const model of models) {
      const v = matrix[cond]?.[model]?.[metric]
      if (v != null) {
        if (metricDef.higher ? v > best : v < best) best = v
      }
    }
    bestPerCond[cond] = best
  }

  return (
    <div className="bm-matrix">
      <div className="bm-matrix-header">
        <span className="bm-matrix-title">
          {conditions.length} conditions · {models.length} models · {runs.length} runs
          {contamFilter && ' · contamination-filtered'}
        </span>
        <div className="bm-matrix-controls">
          {/* Metric selector */}
          <select
            className="bm-metric-select"
            value={metric}
            onChange={e => setMetric(e.target.value)}
            title="Select metric to display"
          >
            {METRICS.map(m => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
          <button
            className={`bm-metric-toggle ${contamFilter ? 'active' : ''}`}
            onClick={() => toggleContamFilter(!contamFilter)}
            title="Exclude questions where estimated_start_time < model knowledge cutoff"
          >
            Contam. filter
          </button>
          <button
            className="bm-metric-toggle"
            onClick={runReasoningEval}
            disabled={evaluating}
            title="Re-run reasoning graph evaluation against hindsight graphs"
            style={{ marginLeft: 8 }}
          >
            {evaluating ? 'Evaluating…' : 'Re-evaluate'}
          </button>
          <button className="bm-refresh-btn" onClick={() => load(contamFilter)} title="Refresh">🔄</button>
        </div>
      </div>

      <div className="bm-table-wrap">
        <table className="bm-table">
          <thead>
            <tr>
              <th className="bm-th-cond">Condition</th>
              {models.map(m => (
                <th key={m} className="bm-th-model" title={m}>
                  {m.split('/').pop()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {conditions.map(cond => (
              <React.Fragment key={cond}>
                <tr className="bm-row">
                  <td className="bm-td-cond">{condLabel(cond)}</td>
                  {models.map(model => {
                    const cell = matrix[cond]?.[model]
                    const key  = `${cond}:${model}`
                    const val  = cell?.[metric]
                    const isBest = val != null && val === bestPerCond[cond]
                    const fromReasoning = metricDef.src === 'reasoning' && val != null
                    return (
                      <td
                        key={model}
                        className={`bm-td-cell ${cell ? 'has-data' : 'no-data'} ${isBest ? 'best' : ''} ${expanded === key ? 'active' : ''} ${fromReasoning ? 'reasoning-src' : ''}`}
                        onClick={() => cell && toggleExpand(cond, model)}
                        title={cell ? `n=${cell.n}` : 'No data'}
                      >
                        {cell ? (
                          <div className="bm-cell-inner">
                            <span className="bm-cell-main">{metricDef.fmt(val)}</span>
                            <span className="bm-cell-n">n={cell.n}</span>
                          </div>
                        ) : (
                          <span className="bm-cell-empty">—</span>
                        )}
                      </td>
                    )
                  })}
                </tr>

                {/* Expanded: per-run detail */}
                {models.map(model => {
                  const key = `${cond}:${model}`
                  if (expanded !== key) return null
                  const runRows = Object.entries(runDetails)
                    .filter(([, d]) => d?.condition_results?.[cond]?.[model])
                    .map(([runId, d]) => {
                      const r   = d.condition_results[cond][model]
                      const run = runs.find(x => x.run_id === runId)
                      return {
                        runId,
                        timestamp: run?.timestamp,
                        accuracy:  r.accuracy,
                        brier:     r.avg_brier_score,
                        n:         r.successful,
                        total:     r.total_questions,
                        failed:    r.failed,
                      }
                    })
                    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
                  return (
                    <tr key={`${key}-detail`} className="bm-expand-row">
                      <td colSpan={models.length + 1} className="bm-expand-cell">
                        <div className="bm-expand-header">
                          <span className="bm-expand-label">
                            {condLabel(cond)} · {model.split('/').pop()}
                          </span>
                          <button className="bm-expand-close" onClick={() => setExpanded(null)}>✕</button>
                        </div>
                        <table className="bm-run-table">
                          <thead>
                            <tr>
                              <th>Run</th><th>Date</th><th>Accuracy</th>
                              <th>Brier</th><th>n (scored)</th><th>Total</th><th>Failed</th>
                            </tr>
                          </thead>
                          <tbody>
                            {runRows.map(r => (
                              <tr key={r.runId}>
                                <td className="bm-run-id" title={r.runId}>{r.runId.slice(-12)}</td>
                                <td>{r.timestamp ? new Date(r.timestamp).toLocaleDateString() : '—'}</td>
                                <td>{r.accuracy != null ? `${(r.accuracy*100).toFixed(1)}%` : '—'}</td>
                                <td>{r.brier != null ? r.brier.toFixed(3) : '—'}</td>
                                <td>{r.n}</td>
                                <td>{r.total ?? '—'}</td>
                                <td>{r.failed ?? 0}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )
                })}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default BenchmarkMatrix
