import React, { useState } from 'react'
import ControlPanel from './ControlPanel'
import QuestionList from './QuestionList'
import DatabaseSelector from './DatabaseSelector'
import GraphVisualization from './GraphVisualization'
import EventDetails from './EventDetails'
import Timeline from './Timeline'
import TimeSeriesChart from './TimeSeriesChart'
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
  onDatabaseChange,
  onShowNeighborhood,
  onTimeRangeChange,
  priceHistoryData,
  loadingPriceHistory,
  questionRelatedEvents,
  priceHistoryInterval,
  setPriceHistoryInterval,
}) {
  const [nestedTab, setNestedTab] = useState('controls') // 'controls' or 'questions'

  return (
    <div className="event-graphs-page">
      {/* Nested tabs */}
      <div className="nested-tabs">
        <button
          className={`nested-tab ${nestedTab === 'controls' ? 'active' : ''}`}
          onClick={() => setNestedTab('controls')}
        >
          ⚙️ Controls
        </button>
        <button
          className={`nested-tab ${nestedTab === 'questions' ? 'active' : ''}`}
          onClick={() => setNestedTab('questions')}
        >
          📋 Questions ({questions.length})
        </button>
      </div>

      {/* Main layout with sidebar and graph */}
      <div className="main-layout">
        <div className="left-sidebar">
          <div className="sidebar-content">
            {nestedTab === 'controls' && (
              <>
                <DatabaseSelector onDatabaseChange={onDatabaseChange} />
                <ControlPanel
                  filters={filters}
                  onFilterChange={onFilterChange}
                  onRefresh={onRefresh}
                  loading={loading}
                  questions={questions}
                  onQuestionFilter={onQuestionFilter}
                />
              </>
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
          <div className="graph-container">
            {loading && <div className="loading">Loading graph...</div>}
            {error && <div className="error">{error}</div>}
            {!loading && !error && (
              <GraphVisualization
                graphData={graphData}
                onNodeClick={onNodeClick}
                selectedNode={selectedNode}
              />
            )}
          </div>

          <Timeline
            graphData={fullGraphData}
            onEventClick={onNodeClick}
            onTimeRangeChange={onTimeRangeChange}
            selectedNode={selectedNode}
          />

          {/* Price history chart for Polymarket questions */}
          {selectedQuestionId && questions.find(q => q.id === selectedQuestionId)?.source === 'polymarket' && (
            <div style={{ marginTop: '20px', padding: '20px', backgroundColor: '#f8f9fa', borderRadius: '8px', minHeight: '100px', border: '1px solid #dee2e6' }}>
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
