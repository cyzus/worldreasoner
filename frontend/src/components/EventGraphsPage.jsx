import React, { useState, useEffect } from 'react'
import ControlPanel from './ControlPanel'
import QuestionList from './QuestionList'
import GraphVisualization from './GraphVisualization'
import EventDetails from './EventDetails'
import Timeline from './Timeline'
import TimeSeriesChart from './TimeSeriesChart'
import ForecastGraph from './ForecastGraph'
import ArticleCoverage from './ArticleCoverage'
import './EventGraphsPage.css'

/**
 * EventGraphsPage - Main event graph visualization with nested controls and questions
 */
function EventGraphsPage({
  fullGraphData,
  graphData,
  selectedNode,
  onNodeClick,
  loading,
  error,
  filters,
  onFilterChange,
  onRefresh,
  questions,
  selectedQuestionId,
  onQuestionFilter,
  onShowNeighborhood,
  onTimeRangeChange,
  priceHistoryData,
  loadingPriceHistory,
  questionRelatedEvents,
  priceHistoryInterval,
  setPriceHistoryInterval,
}) {
  const [nestedTab, setNestedTab] = useState('controls') // 'controls' or 'questions'

  // Graph force settings (moved from GraphVisualization)
  const [forceSettings, setForceSettings] = useState({
    linkDistance: 40,        // Shorter distance = tighter layout (was 70)
    linkStrength: 1,         // Normal spring strength
    chargeStrength: -200,    // Less repulsion = closer nodes (was -200)
    centerStrength: 0.05     // Very gentle center force (like in examples)
  })

  // Forecast graph state
  const [forecasts, setForecasts] = useState([])
  const [selectedForecastId, setSelectedForecastId] = useState(null)
  const [forecastGraphData, setForecastGraphData] = useState(null)
  const [loadingForecastGraph, setLoadingForecastGraph] = useState(false)
  const [loadingForecasts, setLoadingForecasts] = useState(false)
  const [forecastsError, setForecastsError] = useState(null)
  const [graphView, setGraphView] = useState('evidence') // 'evidence', 'forecast', 'both'

  // Fetch forecasts for the selected question
  useEffect(() => {
    if (!selectedQuestionId) {
      setForecasts([])
      setSelectedForecastId(null)
      setForecastGraphData(null)
      setGraphView('evidence')
      setForecastsError(null)
      return
    }

    // Fetch forecasts for this question
    setLoadingForecasts(true)
    setForecastsError(null)

    fetch(`http://localhost:8018/api/questions/${selectedQuestionId}/forecasts`)
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`)
        }
        return res.json()
      })
      .then(data => {
        setForecasts(data.forecasts || [])
        // Auto-select first forecast if available
        if (data.forecasts && data.forecasts.length > 0) {
          setSelectedForecastId(data.forecasts[0].id)
        } else {
          setSelectedForecastId(null)
          setForecastGraphData(null)
        }
      })
      .catch(err => {
        console.error('Error fetching forecasts:', err)
        setForecastsError(err.message)
        setForecasts([])
      })
      .finally(() => {
        setLoadingForecasts(false)
      })
  }, [selectedQuestionId])

  // Fetch forecast graph data when forecast is selected
  useEffect(() => {
    if (!selectedForecastId) {
      setForecastGraphData(null)
      return
    }

    setLoadingForecastGraph(true)
    fetch(`http://localhost:8018/api/forecasts/${selectedForecastId}/graph`)
      .then(res => {
        if (!res.ok) {
          if (res.status === 404) {
            // No graph data available for this forecast
            setForecastGraphData(null)
            return null
          }
          throw new Error(`HTTP ${res.status}`)
        }
        return res.json()
      })
      .then(data => {
        if (data) {
          setForecastGraphData(data)
        }
      })
      .catch(err => {
        console.error('Error fetching forecast graph:', err)
        setForecastGraphData(null)
      })
      .finally(() => {
        setLoadingForecastGraph(false)
      })
  }, [selectedForecastId])

  return (
    <div className="event-graphs-page">
      {/* Nested tabs */}
      <div className="nested-tabs">
        <button
          className={`nested-tab ${nestedTab === 'questions' ? 'active' : ''}`}
          onClick={() => setNestedTab('questions')}
        >
          📋 Questions ({questions.length})
        </button>
        <button
          className={`nested-tab ${nestedTab === 'controls' ? 'active' : ''}`}
          onClick={() => setNestedTab('controls')}
        >
          ⚙️ Controls
        </button>
      </div>

      {/* Main layout with sidebar and graph */}
      <div className="main-layout">
        <div className="left-sidebar">
          <div className="sidebar-content">
            {nestedTab === 'controls' && (
              <ControlPanel
                filters={filters}
                onFilterChange={onFilterChange}
                onRefresh={onRefresh}
                loading={loading}
                questions={questions}
                onQuestionFilter={onQuestionFilter}
                forceSettings={forceSettings}
                onForceChange={setForceSettings}
              />
            )}

            {nestedTab === 'questions' && (
              <QuestionList
                questions={questions}
                selectedQuestionId={selectedQuestionId}
                onQuestionSelect={(questionId) => {
                  onQuestionFilter(questionId)
                }}
                onClose={() => setNestedTab('controls')}
              />
            )}
          </div>
        </div>

        <div className="graph-main">
          {/* Forecast controls - show when question is selected */}
          {selectedQuestionId && (
            <div style={{
              display: 'flex',
              gap: '16px',
              padding: '12px 16px',
              backgroundColor: '#f8f9fa',
              borderRadius: '8px',
              alignItems: 'center',
              flexWrap: 'wrap',
              flexShrink: 0
            }}>
              {/* Loading state */}
              {loadingForecasts && (
                <span style={{ fontSize: '14px', color: '#495057' }}>
                  Loading forecasts...
                </span>
              )}

              {/* Error state */}
              {!loadingForecasts && forecastsError && (
                <span style={{ fontSize: '14px', color: '#dc3545' }}>
                  Error loading forecasts: {forecastsError}
                </span>
              )}

              {/* No forecasts */}
              {!loadingForecasts && !forecastsError && forecasts.length === 0 && (
                <span style={{ fontSize: '14px', color: '#6c757d', fontStyle: 'italic' }}>
                  No forecasts available for this question. Run a forecast to see causal reasoning graphs.
                </span>
              )}

              {/* Forecast controls - show when forecasts available */}
              {!loadingForecasts && forecasts.length > 0 && (
                <>
                  {/* Forecast selector */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <label style={{ fontSize: '14px', fontWeight: '500', color: '#495057' }}>
                      Forecast:
                    </label>
                    <select
                      value={selectedForecastId || ''}
                      onChange={(e) => setSelectedForecastId(e.target.value)}
                      style={{
                        padding: '6px 12px',
                        borderRadius: '4px',
                        border: '1px solid #ced4da',
                        fontSize: '14px'
                      }}
                    >
                      {forecasts.map(forecast => (
                        <option key={forecast.id} value={forecast.id}>
                          {new Date(forecast.created_at).toLocaleString()} - {forecast.mode}
                          {forecast.probability !== null && ` (${(forecast.probability * 100).toFixed(1)}%)`}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Graph view selector */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <label style={{ fontSize: '14px', fontWeight: '500', color: '#495057' }}>
                      View:
                    </label>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <button
                        onClick={() => setGraphView('evidence')}
                        style={{
                          padding: '6px 12px',
                          backgroundColor: graphView === 'evidence' ? '#4CAF50' : '#fff',
                          color: graphView === 'evidence' ? '#fff' : '#495057',
                          border: `1px solid ${graphView === 'evidence' ? '#4CAF50' : '#ced4da'}`,
                          borderRadius: '4px',
                          fontSize: '13px',
                          cursor: 'pointer',
                          fontWeight: graphView === 'evidence' ? '500' : 'normal'
                        }}
                      >
                        Evidence Graph
                      </button>
                      <button
                        onClick={() => setGraphView('forecast')}
                        disabled={!forecastGraphData}
                        style={{
                          padding: '6px 12px',
                          backgroundColor: graphView === 'forecast' ? '#4CAF50' : '#fff',
                          color: graphView === 'forecast' ? '#fff' : '#495057',
                          border: `1px solid ${graphView === 'forecast' ? '#4CAF50' : '#ced4da'}`,
                          borderRadius: '4px',
                          fontSize: '13px',
                          cursor: forecastGraphData ? 'pointer' : 'not-allowed',
                          fontWeight: graphView === 'forecast' ? '500' : 'normal',
                          opacity: forecastGraphData ? 1 : 0.5
                        }}
                      >
                        Forecast Reasoning
                      </button>
                      <button
                        onClick={() => setGraphView('both')}
                        disabled={!forecastGraphData}
                        style={{
                          padding: '6px 12px',
                          backgroundColor: graphView === 'both' ? '#4CAF50' : '#fff',
                          color: graphView === 'both' ? '#fff' : '#495057',
                          border: `1px solid ${graphView === 'both' ? '#4CAF50' : '#ced4da'}`,
                          borderRadius: '4px',
                          fontSize: '13px',
                          cursor: forecastGraphData ? 'pointer' : 'not-allowed',
                          fontWeight: graphView === 'both' ? '500' : 'normal',
                          opacity: forecastGraphData ? 1 : 0.5
                        }}
                      >
                        Both Side-by-Side
                      </button>
                    </div>
                  </div>

                  {/* Status indicator */}
                  {loadingForecastGraph && (
                    <span style={{ fontSize: '13px', color: '#6c757d' }}>
                      Loading forecast graph...
                    </span>
                  )}
                  {!loadingForecastGraph && !forecastGraphData && selectedForecastId && (
                    <span style={{ fontSize: '13px', color: '#6c757d', fontStyle: 'italic' }}>
                      No causal reasoning graph available for this forecast
                    </span>
                  )}
                </>
              )}
            </div>
          )}

          {/* Article Coverage Analysis */}
          {selectedQuestionId && (
            <ArticleCoverage questionId={selectedQuestionId} />
          )}

          {/* Graph display area */}
          <div style={{
            height: '600px',
            display: 'flex',
            gap: '16px',
            flexDirection: graphView === 'both' ? 'row' : 'column',
            overflow: graphView === 'both' ? 'auto' : 'hidden',
            flexShrink: 0
          }}>
            {/* Evidence collection graph */}
            {(graphView === 'evidence' || graphView === 'both') && (
              <div className="graph-container" style={{
                flex: 1,
                minWidth: graphView === 'both' ? '400px' : 'auto',
                minHeight: 0,
                overflow: 'hidden'
              }}>
                <h4 style={{
                  margin: '0 0 12px 0',
                  fontSize: '16px',
                  fontWeight: '600',
                  display: graphView === 'both' ? 'block' : 'none'
                }}>
                  Evidence Collection Graph
                </h4>
                {loading && <div className="loading">Loading graph...</div>}
                {error && <div className="error">{error}</div>}
                {!loading && !error && (
                  <GraphVisualization
                    graphData={graphData}
                    onNodeClick={onNodeClick}
                    selectedNode={selectedNode}
                    forceSettings={forceSettings}
                  />
                )}
              </div>
            )}

            {/* Forecast reasoning graph */}
            {(graphView === 'forecast' || graphView === 'both') && (
              <div className="graph-container" style={{
                flex: 1,
                minWidth: graphView === 'both' ? '400px' : 'auto',
                minHeight: 0,
                overflow: 'hidden'
              }}>
                <h4 style={{
                  margin: '0 0 12px 0',
                  fontSize: '16px',
                  fontWeight: '600',
                  display: graphView === 'both' ? 'block' : 'none'
                }}>
                  Forecast Reasoning Graph
                </h4>
                {loadingForecastGraph && (
                  <div className="loading">Loading forecast graph...</div>
                )}
                {!loadingForecastGraph && forecastGraphData && (
                  <ForecastGraph graphData={forecastGraphData} />
                )}
                {!loadingForecastGraph && !forecastGraphData && (
                  <div style={{
                    padding: '40px',
                    textAlign: 'center',
                    color: '#6c757d',
                    border: '1px solid #dee2e6',
                    borderRadius: '8px',
                    backgroundColor: '#f8f9fa'
                  }}>
                    <p>No causal reasoning graph available for this forecast.</p>
                    <p style={{ fontSize: '14px', color: '#adb5bd', marginTop: '8px' }}>
                      Enable "Causal Reasoning Tools" when running forecasts to build causal graphs.
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          <div style={{ flexShrink: 0 }}>
            <Timeline
              graphData={fullGraphData}
              onEventClick={onNodeClick}
              onTimeRangeChange={onTimeRangeChange}
              selectedNode={selectedNode}
              selectedQuestionId={selectedQuestionId}
              questionRelatedEvents={questionRelatedEvents}
            />
          </div>

          {/* Price history chart for Polymarket questions */}
          {selectedQuestionId && questions.find(q => q.id === selectedQuestionId)?.source === 'polymarket' && (
            <div style={{ padding: '20px', backgroundColor: '#f8f9fa', borderRadius: '8px', minHeight: '100px', border: '1px solid #dee2e6', flexShrink: 0 }}>
              {/* Time interval controls - always visible */}
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '10px 20px 0 20px',
                gap: '10px',
                borderBottom: '1px solid #333',
                paddingBottom: '10px',
                marginBottom: '10px'
              }}>
                <div style={{ color: '#888', fontSize: '12px', fontStyle: 'italic' }}>
                  {!loadingPriceHistory && priceHistoryData && priceHistoryData.price_history && (() => {
                    // Calculate actual date range from price data
                    const allTimestamps = []
                    Object.values(priceHistoryData.price_history).forEach(history => {
                      history.forEach(point => allTimestamps.push(point.t * 1000))
                    })
                    if (allTimestamps.length > 0) {
                      const minDate = new Date(Math.min(...allTimestamps))
                      const maxDate = new Date(Math.max(...allTimestamps))
                      const daysDiff = Math.ceil((maxDate - minDate) / (1000 * 60 * 60 * 24))
                      return `Showing ${daysDiff + 1} day${daysDiff !== 0 ? 's' : ''} of market data`
                    }
                    return ''
                  })()}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{ color: '#999', fontSize: '13px' }}>Time Range:</span>
                  {['max', '1w', '1d', '6h', '1h', '1m'].map(interval => (
                    <button
                      key={interval}
                      onClick={() => setPriceHistoryInterval(interval)}
                      disabled={loadingPriceHistory}
                      style={{
                        padding: '6px 12px',
                        backgroundColor: priceHistoryInterval === interval ? '#4CAF50' : '#333',
                        color: priceHistoryInterval === interval ? '#fff' : '#ddd',
                        border: priceHistoryInterval === interval ? '2px solid #4CAF50' : '1px solid #555',
                        borderRadius: '4px',
                        cursor: loadingPriceHistory ? 'not-allowed' : 'pointer',
                        fontSize: '12px',
                        fontWeight: priceHistoryInterval === interval ? 'bold' : 'normal',
                        transition: 'all 0.2s',
                        opacity: loadingPriceHistory ? 0.5 : 1
                      }}
                      onMouseEnter={(e) => {
                        if (priceHistoryInterval !== interval && !loadingPriceHistory) {
                          e.target.style.backgroundColor = '#444'
                          e.target.style.borderColor = '#666'
                        }
                      }}
                      onMouseLeave={(e) => {
                        if (priceHistoryInterval !== interval && !loadingPriceHistory) {
                          e.target.style.backgroundColor = '#333'
                          e.target.style.borderColor = '#555'
                        }
                      }}
                    >
                      {interval === 'max' ? 'All' : interval.toUpperCase()}
                    </button>
                  ))}
                </div>
              </div>

              {/* Loading state */}
              {loadingPriceHistory && (
                <div style={{ color: '#495057', textAlign: 'center', padding: '40px', fontSize: '15px', fontWeight: 500 }}>
                  ⏳ Loading market price history...
                </div>
              )}

              {/* Chart display */}
              {!loadingPriceHistory && priceHistoryData && priceHistoryData.price_history && Object.keys(priceHistoryData.price_history).length > 0 && (
                <TimeSeriesChart
                  priceHistory={priceHistoryData.price_history}
                  events={questionRelatedEvents}
                  targetEventId={questions.find(q => q.id === selectedQuestionId)?.target_event_id}
                  outcomes={priceHistoryData.outcomes || ['Yes', 'No']}
                />
              )}

              {/* Error/no data state */}
              {!loadingPriceHistory && (!priceHistoryData || !priceHistoryData.price_history || Object.keys(priceHistoryData.price_history).length === 0) && (
                <div style={{ color: '#6c757d', textAlign: 'center', padding: '40px', fontSize: '14px' }}>
                  ℹ️ No price data available for this time range
                  <br />
                  <span style={{ fontSize: '12px', color: '#adb5bd' }}>
                    Try selecting a different time range above
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {selectedNode && (
          <EventDetails
            node={selectedNode}
            onClose={() => onNodeClick(null)}
            onShowNeighborhood={onShowNeighborhood}
          />
        )}
      </div>
    </div>
  )
}

export default EventGraphsPage
