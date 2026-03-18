import React, { useState } from 'react'
import QuestionList from './QuestionList'
import EventDetails from './EventDetails'
import CaseStudyView from './CaseStudyView'
import CanvasTimelineGraph from './CanvasTimelineGraph'

import TimeSeriesChart from './TimeSeriesChart'
import ForecastGraph from './ForecastGraph'
import QuestionStatistics from './QuestionStatistics'
import ArticleCoverage from './ArticleCoverage'
import CausalPathProgress from './CausalPathProgress'
import { useForecasts } from '../hooks/useForecasts'
import { useGraphStore } from '../stores/graphStore'
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
  onQuestionUpdated,
  onQuestionDeleted,
  timeFilter,
}) {
  const [presentationMode, setPresentationMode] = useState('casestudy') // 'casestudy' or 'graph'
  const [showStatistics, setShowStatistics] = useState(false)

  // Outcome impacts toggle (from graph store)
  const includeOutcomes = useGraphStore(state => state.includeOutcomes)
  const setIncludeOutcomes = useGraphStore(state => state.setIncludeOutcomes)

  // Graph force settings (MOVED TO LEGACY - kept for compatibility if needed elsewhere but not used here)
  const [forceSettings, setForceSettings] = useState({
    linkDistance: 40,
    linkStrength: 1,
    chargeStrength: -200,
    centerStrength: 0.05
  })

  // Use custom hook for forecasts
  const {
    forecasts,
    selectedForecastId,
    setSelectedForecastId,
    forecastGraphData,
    loadingForecastGraph,
    loadingForecasts,
    forecastsError,
    graphView,
    setGraphView
  } = useForecasts(selectedQuestionId)

  return (
    <div className="event-graphs-page page-container">
      <div className="event-toolbar">
        <div className="event-toolbar-left">
          <h2 className="event-toolbar-title">Event Graph Explorer</h2>
          <span className="event-toolbar-count">{questions.length} questions</span>
        </div>
        <div className="event-toolbar-actions">
          <button
            className={`event-toolbar-btn ${showStatistics ? 'active' : ''}`}
            onClick={() => setShowStatistics(prev => !prev)}
          >
            {showStatistics ? 'Hide Statistics' : 'Show Statistics'}
          </button>
        </div>
      </div>

      {/* Main layout with sidebar and graph */}
      <div className="page-content">
        <div className="page-sidebar">
          <div className="scroll-container">
            <QuestionList
              questions={questions}
              selectedQuestionId={selectedQuestionId}
              statusFilterVariant="eventgraph"
              onQuestionSelect={(questionId) => {
                onQuestionFilter(questionId)
              }}
              onClose={() => { }}
              onQuestionUpdated={onQuestionUpdated}
              onQuestionDeleted={onQuestionDeleted}
            />
          </div>
        </div>

        <div className="page-main event-main">
          {showStatistics && (
            <div className="event-statistics-panel">
              <QuestionStatistics questions={questions} />
            </div>
          )}

          {/* Top Bar for Graph/Case Study Toggle */}
          {selectedQuestionId && (
            <div className="event-view-toggle-row">
              <div className="view-toggle-group">
                <button
                  onClick={() => setPresentationMode('graph')}
                  className={presentationMode === 'graph' ? 'active' : ''}
                >
                  Interactive Graph
                </button>
                <button
                  onClick={() => setPresentationMode('casestudy')}
                  className={presentationMode === 'casestudy' ? 'active' : ''}
                >
                  Case Study
                </button>
              </div>
            </div>
          )}

          <>
            {/* Forecast controls - show when question is selected */}
            {selectedQuestionId && presentationMode === 'graph' && (
                <div style={{
                  display: 'flex',
                  gap: '16px',
                  padding: '12px 16px',
                  backgroundColor: '#f8f9fa',
                  borderRadius: '8px',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  flexShrink: 0,
                  marginBottom: '16px',
                  border: '1px solid #dee2e6'
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

              {/* Causal Path Progress */}
              {selectedQuestionId && (
                <div style={{ flexShrink: 0 }}>
                  <CausalPathProgress questionId={selectedQuestionId} />
                </div>
              )}

              {/* Article Coverage Analysis */}
              {selectedQuestionId && presentationMode === 'graph' && (
                <div style={{ flexShrink: 0 }}>
                  <ArticleCoverage questionId={selectedQuestionId} />
                </div>
              )}

              {/* Main Content Area (Graph or Case Study) */}
              {!selectedQuestionId ? (
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  minHeight: '500px',
                  height: '60vh',
                  backgroundColor: '#f8f9fa',
                  border: '1px dashed #dee2e6',
                  borderRadius: '8px',
                  color: '#6c757d',
                  flexDirection: 'column',
                  marginBottom: '16px'
                }}>
                  <div style={{ fontSize: '48px', marginBottom: '16px' }}>👈</div>
                  <h3 style={{ margin: '0 0 8px 0', color: '#495057' }}>Select a Question</h3>
                  <p style={{ margin: 0 }}>Choose a question from the sidebar to view its Case Study and details</p>
                </div>
              ) : presentationMode === 'casestudy' ? (
                <CaseStudyView
                  graphData={graphData}
                  selectedQuestion={questions.find(q => q.id === selectedQuestionId)}
                />
              ) : (
                <div style={{
                  flex: '0 0 auto',
                  display: 'flex',
                  gap: '16px',
                  flexDirection: graphView === 'both' ? 'row' : 'column',
                  flexWrap: graphView === 'both' ? 'wrap' : 'nowrap',
                  minHeight: '500px',
                  height: '60vh',
                  marginBottom: '16px'
                }}>
                  {/* Evidence collection graph */}
                  {(graphView === 'evidence' || graphView === 'both') && (
                    <div className="graph-container" style={{
                      flex: 1,
                      minWidth: graphView === 'both' ? 'min(400px, 100%)' : '0',
                      minHeight: 0,
                      overflow: 'hidden',
                      display: 'flex',
                      flexDirection: 'column'
                    }}>
                      <div style={{ padding: '12px 16px', borderBottom: '1px solid #eee', background: '#fff' }}>
                        <h4 style={{ margin: 0, fontSize: '15px', fontWeight: '600', color: '#333' }}>
                          Evidence Timeline
                        </h4>
                      </div>
                      <div className="graph-main" style={{ flex: 1, position: 'relative' }}>
                        {loading && <div className="loading">Loading graph...</div>}
                        {error && <div className="error">{error}</div>}
                        {!loading && !error && (
                          <>
                            <CanvasTimelineGraph
                              key={`evidence-${graphView}-${selectedQuestionId || 'none'}`}
                              graphData={graphData}
                              onNodeClick={onNodeClick}
                              selectedNode={selectedNode}
                              timeFilter={timeFilter}
                            />


                          </>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Forecast reasoning graph */}
                  {(graphView === 'forecast' || graphView === 'both') && (
                    <div className="graph-container" style={{
                      flex: 1,
                      minWidth: graphView === 'both' ? 'min(400px, 100%)' : '0',
                      minHeight: 0,
                      overflow: 'hidden',
                      display: 'flex',
                      flexDirection: 'column'
                    }}>
                      <div style={{ padding: '12px 16px', borderBottom: '1px solid #eee', background: '#fff' }}>
                        <h4 style={{ margin: 0, fontSize: '15px', fontWeight: '600', color: '#333' }}>
                          Forecast Reasoning Timeline
                        </h4>
                      </div>
                      <div className="graph-main" style={{ flex: 1, position: 'relative' }}>
                        {loadingForecastGraph && (
                          <div className="loading">Loading forecast graph...</div>
                        )}
                        {!loadingForecastGraph && forecastGraphData && (
                          <ForecastGraph
                            key={`forecast-${graphView}-${selectedQuestionId || 'none'}`}
                            graphData={forecastGraphData}
                            onNodeClick={onNodeClick}
                            selectedNode={selectedNode}
                          />
                        )}
                        {!loadingForecastGraph && !forecastGraphData && (
                          <div style={{
                            padding: '40px',
                            textAlign: 'center',
                            color: '#6c757d',
                            backgroundColor: '#f8f9fa',
                            height: '100%',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'center'
                          }}>
                            <p>No causal reasoning graph available.</p>
                            <p style={{ fontSize: '13px', color: '#adb5bd', marginTop: '8px' }}>
                              Run a forecast with "Causal Reasoning" enabled.
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )} {/* End of presentation mode conditionally rendered block */}



              {/* Price history chart for Polymarket questions - Simplified UI */}
              {selectedQuestionId && questions.find(q => q.id === selectedQuestionId)?.source === 'polymarket' && (
                <div style={{ flexShrink: 0, marginTop: '16px' }}>
                  {!loadingPriceHistory && priceHistoryData && priceHistoryData.price_history && Object.keys(priceHistoryData.price_history).length > 0 && (
                    <TimeSeriesChart
                      priceHistory={priceHistoryData.price_history}
                      events={questionRelatedEvents}
                      turningPoints={priceHistoryData.turning_points || []}
                      leadChanges={priceHistoryData.lead_changes || []}
                      outcomes={priceHistoryData.outcomes || ['Yes', 'No']}
                      tokenOutcomes={priceHistoryData.token_outcomes || {}}
                      activeInterval={priceHistoryInterval}
                      onIntervalChange={setPriceHistoryInterval}
                    />
                  )}

                  {/* Loading state - only show if no data yet */}
                  {loadingPriceHistory && (!priceHistoryData || !priceHistoryData.price_history) && (
                    <div className="price-history-loading">
                      ⏳ Loading market price history...
                    </div>
                  )}

                  {/* Error/no data state */}
                  {!loadingPriceHistory && (!priceHistoryData || !priceHistoryData.price_history || Object.keys(priceHistoryData.price_history).length === 0) && (
                    <div className="price-history-empty">
                      ℹ️ No price data available for this Question
                    </div>
                  )}
                </div>
              )}
          </>

        </div>
      </div>

      {selectedNode && (
        <EventDetails
          node={selectedNode}
          onClose={() => onNodeClick(null)}
          onShowNeighborhood={onShowNeighborhood}
        />
      )}
    </div>
  )
}

export default EventGraphsPage
