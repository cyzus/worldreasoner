import React, { useState, useEffect, useCallback } from 'react'
import { fetchBenchmarkResults, fetchBenchmarkResult, fetchBenchmarkResultFiltered } from '../../api/graphApi'
import './BenchmarkMatrix.css'

const pct  = v => (v != null ? `${(v * 100).toFixed(1)}%` : '—')
const brier = v => (v != null ? v.toFixed(3) : '—')

/**
 * Build condition×model map using the LATEST run for each (condition, model) cell.
 * Runs are sorted newest-first so the first match wins — no double-counting across runs.
 */
function aggregateRuns(runs, runDetails) {
  // Sort runs newest-first so we always take the most recent result per cell
  const sortedRunIds = [...runs]
    .sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0))
    .map(r => r.run_id)

  // Map: condition -> model -> result from the most recent run that has that cell
  const latest = {}

  for (const runId of sortedRunIds) {
    const detail = runDetails[runId]
    if (!detail) continue
    const condResults = detail.condition_results || {}
    for (const [cond, modelMap] of Object.entries(condResults)) {
      if (!latest[cond]) latest[cond] = {}
      for (const [model, result] of Object.entries(modelMap)) {
        // Only take this cell if we haven't seen a newer one already
        if (!latest[cond][model]) {
          latest[cond][model] = { ...result, runId }
        }
      }
    }
  }

  // Convert to display format
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

const BenchmarkMatrix = ({ onRefresh }) => {
  const [runs, setRuns]               = useState([])
  const [runDetails, setRunDetails]   = useState({})
  const [loading, setLoading]         = useState(false)
  const [filtering, setFiltering]     = useState(false) // loading contamination filter
  const [error, setError]             = useState(null)
  const [expanded, setExpanded]       = useState(null)
  const [showBrier, setShowBrier]     = useState(false)
  const [contamFilter, setContamFilter] = useState(true) // on by default — matches paper

  const load = useCallback(async (withFilter = true) => {
    setLoading(true)
    setError(null)
    try {
      const list = await fetchBenchmarkResults()
      setRuns(list)
      // Fetch filtered or unfiltered depending on current mode
      const fetcher = withFilter ? fetchBenchmarkResultFiltered : fetchBenchmarkResult
      const details = await Promise.all(
        list.map(r => fetcher(r.run_id).catch(() =>
          // Filtered endpoint may fail if no detailed_results; fall back to unfiltered
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

  const toggleContamFilter = useCallback((val) => {
    setContamFilter(val)
    load(val)
  }, [load])

  useEffect(() => { load(true) }, [load]) // initial load with filter on

  if (loading) return <div className="bm-state">Loading results…</div>
  if (error)   return <div className="bm-state error">{error}</div>
  if (runs.length === 0) return (
    <div className="bm-state muted">
      No benchmark results yet. Run a benchmark to see results here.
    </div>
  )

  const matrix = aggregateRuns(runs, runDetails)
  const conditions = Object.keys(matrix).sort()
  const models = [...new Set(
    Object.values(matrix).flatMap(m => Object.keys(m))
  )].sort()

  if (conditions.length === 0) {
    return <div className="bm-state muted">Results loaded but no condition data found.</div>
  }

  const toggleExpand = (cond, model) => {
    const key = `${cond}:${model}`
    setExpanded(prev => prev === key ? null : key)
  }

  // Find best accuracy per condition for highlighting
  const bestPerCond = {}
  for (const cond of conditions) {
    let best = -Infinity
    for (const model of models) {
      const v = matrix[cond]?.[model]?.accuracy
      if (v != null && v > best) best = v
    }
    bestPerCond[cond] = best
  }

  return (
    <div className="bm-matrix">
      <div className="bm-matrix-header">
        <span className="bm-matrix-title">
          {conditions.length} conditions · {models.length} models · {runs.length} runs
          {contamFilter && ' · contamination-filtered'}
          {filtering && ' · filtering…'}
        </span>
        <div className="bm-matrix-controls">
          <button
            className={`bm-metric-toggle ${!showBrier ? 'active' : ''}`}
            onClick={() => setShowBrier(false)}
          >Accuracy</button>
          <button
            className={`bm-metric-toggle ${showBrier ? 'active' : ''}`}
            onClick={() => setShowBrier(true)}
          >Brier</button>
          <button
            className={`bm-metric-toggle ${contamFilter ? 'active' : ''}`}
            onClick={() => toggleContamFilter(!contamFilter)}
            title="Exclude questions where estimated_start_time < model knowledge cutoff"
            style={{ marginLeft: 8 }}
          >
            {filtering ? '…' : 'Contam. filter'}
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
                  <td className="bm-td-cond">{cond.replace(/_/g, ' ')}</td>
                  {models.map(model => {
                    const cell = matrix[cond]?.[model]
                    const key  = `${cond}:${model}`
                    const isBest = !showBrier && cell?.accuracy === bestPerCond[cond] && cell?.accuracy != null
                    return (
                      <td
                        key={model}
                        className={`bm-td-cell ${cell ? 'has-data' : 'no-data'} ${isBest ? 'best' : ''} ${expanded === key ? 'active' : ''}`}
                        onClick={() => cell && toggleExpand(cond, model)}
                        title={cell ? `n=${cell.n}` : 'No data'}
                      >
                        {cell ? (
                          <div className="bm-cell-inner">
                            <span className="bm-cell-main">
                              {showBrier ? brier(cell.brier) : pct(cell.accuracy)}
                            </span>
                            <span className="bm-cell-n">n={cell.n}</span>
                          </div>
                        ) : (
                          <span className="bm-cell-empty">—</span>
                        )}
                      </td>
                    )
                  })}
                </tr>

                {/* Expanded row: per-run detail for this condition */}
                {models.map(model => {
                  const key = `${cond}:${model}`
                  if (expanded !== key) return null

                  // Find per-run data for this cell
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
                        n:         r.successful,    // denominator for accuracy
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
                            {cond.replace(/_/g, ' ')} · {model.split('/').pop()}
                          </span>
                          <button className="bm-expand-close" onClick={() => setExpanded(null)}>✕</button>
                        </div>
                        <table className="bm-run-table">
                          <thead>
                            <tr>
                              <th>Run</th>
                              <th>Date</th>
                              <th>Accuracy</th>
                              <th>Brier</th>
                              <th>n (scored)</th>
                              <th>Total</th>
                              <th>Failed</th>
                            </tr>
                          </thead>
                          <tbody>
                            {runRows.map(r => (
                              <tr key={r.runId}>
                                <td className="bm-run-id" title={r.runId}>
                                  {r.runId.slice(-12)}
                                </td>
                                <td>{r.timestamp ? new Date(r.timestamp).toLocaleDateString() : '—'}</td>
                                <td>{pct(r.accuracy)}</td>
                                <td>{brier(r.brier)}</td>
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
