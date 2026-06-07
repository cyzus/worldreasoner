import React, { useState } from 'react'
import CanvasTimelineGraph from '../CanvasTimelineGraph'
import ForecastGraph from '../ForecastGraph'
import CausalPathProgress from '../CausalPathProgress'
import { useForecasts } from '../../hooks/useForecasts'
import './QuestionGraphTab.css'


const QuestionGraphTab = ({
  question,
  graphData,
  selectedNode,
  onNodeClick,
  loading,
  error,
  onShowNeighborhood,
  timeFilter,
}) => {
  const [graphView, setGraphViewLocal] = useState('evidence') // 'evidence' | 'forecast' | 'both'

  const {
    forecasts,
    selectedForecastId,
    setSelectedForecastId,
    forecastGraphData,
    loadingForecastGraph,
    loadingForecasts,
    forecastsError,
  } = useForecasts(question?.id)

  return (
    <div className="qgt">
      {/* Controls bar — only toggle + forecast selector (fixed height) */}
      <div className="qgt-controls">
        <div className="qgt-controls-row">
          <div className="qgt-toggle-group">
            {['evidence', 'forecast', 'both'].map(v => (
              <button
                key={v}
                className={`qgt-toggle-btn ${graphView === v ? 'active' : ''}`}
                onClick={() => setGraphViewLocal(v)}
                disabled={v !== 'evidence' && !forecastGraphData}
              >
                {v === 'evidence' ? 'Evidence' : v === 'forecast' ? 'Forecast' : 'Both'}
              </button>
            ))}
          </div>

          {!loadingForecasts && forecasts.length > 0 && (
            <div className="qgt-forecast-select">
              <label>Forecast:</label>
              <select
                value={selectedForecastId || ''}
                onChange={e => setSelectedForecastId(e.target.value)}
              >
                {forecasts.map(f => (
                  <option key={f.id} value={f.id}>
                    {new Date(f.created_at).toLocaleString()} · {f.mode}
                    {f.probability != null && ` · ${(f.probability * 100).toFixed(1)}%`}
                  </option>
                ))}
              </select>
            </div>
          )}

          {loadingForecasts && <span className="qgt-status">Loading forecasts…</span>}
          {!loadingForecasts && forecastsError && (
            <span className="qgt-status error">{forecastsError}</span>
          )}
          {!loadingForecasts && !forecastsError && forecasts.length === 0 && (
            <span className="qgt-status muted">No forecasts yet.</span>
          )}
        </div>

        {/* Causal path progress is compact enough to stay here */}
        <CausalPathProgress questionId={question.id} />
      </div>

      {/* Graph area */}
      <div className={`qgt-graphs ${graphView === 'both' ? 'split' : ''}`}>
        {/* Evidence timeline */}
        {(graphView === 'evidence' || graphView === 'both') && (
          <div className="qgt-graph-pane">
            <div className="qgt-pane-header">Evidence Timeline</div>
            <div className="qgt-pane-body">
              {loading && <div className="qgt-state">Loading graph…</div>}
              {error && <div className="qgt-state error">{error}</div>}
              {!loading && !error && (
                <CanvasTimelineGraph
                  key={`evidence-${graphView}-${question.id}`}
                  graphData={graphData}
                  onNodeClick={onNodeClick}
                  selectedNode={selectedNode}
                  timeFilter={timeFilter}
                  onShowNeighborhood={onShowNeighborhood}
                />
              )}
            </div>
          </div>
        )}

        {/* Forecast reasoning */}
        {(graphView === 'forecast' || graphView === 'both') && (
          <div className="qgt-graph-pane">
            <div className="qgt-pane-header">Forecast Reasoning</div>
            <div className="qgt-pane-body">
              {loadingForecastGraph && <div className="qgt-state">Loading forecast graph…</div>}
              {!loadingForecastGraph && forecastGraphData && (
                <ForecastGraph
                  key={`forecast-${graphView}-${question.id}`}
                  graphData={forecastGraphData}
                  onNodeClick={onNodeClick}
                  selectedNode={selectedNode}
                />
              )}
              {!loadingForecastGraph && !forecastGraphData && (
                <div className="qgt-state muted">
                  No causal reasoning graph available.<br />
                  <small>Run a forecast with causal tools enabled.</small>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

    </div>
  )
}

export default QuestionGraphTab
