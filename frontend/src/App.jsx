import React, { Suspense, useCallback, lazy } from 'react'
import DatabaseDropdown from './components/DatabaseDropdown'
import { useGraphStore } from './stores/graphStore'
import { useQuestionStore } from './stores/questionStore'
import { useUIStore } from './stores/uiStore'
import { useGraphTraversal } from './hooks/useGraphTraversal'
import { useAppData } from './hooks/useAppData'
import './App.css'

// Lazy load heavy page components for code splitting
const PipelinePage = lazy(() => import('./components/PipelinePage'))
const QuestionCollectionPage = lazy(() => import('./components/QuestionCollectionPage'))
const ForecastPage = lazy(() => import('./components/ForecastPage'))
const BenchmarkPage = lazy(() => import('./components/BenchmarkPage'))
const EventGraphsPage = lazy(() => import('./components/EventGraphsPage'))


function App() {
  // Graph store
  const fullGraphData = useGraphStore(state => state.fullGraphData)
  const graphData = useGraphStore(state => state.graphData)
  const selectedNode = useGraphStore(state => state.selectedNode)
  const setSelectedNode = useGraphStore(state => state.setSelectedNode)
  const loading = useGraphStore(state => state.loading)
  const error = useGraphStore(state => state.error)
  const filters = useGraphStore(state => state.filters)
  const timeFilter = useGraphStore(state => state.timeFilter)
  const setTimeFilter = useGraphStore(state => state.setTimeFilter)

  // Question store
  const selectedQuestionId = useQuestionStore(state => state.selectedQuestionId)
  const setSelectedQuestionId = useQuestionStore(state => state.setSelectedQuestion)
  const priceHistoryData = useQuestionStore(state => state.priceHistoryData)
  const loadingPriceHistory = useQuestionStore(state => state.loadingPriceHistory)
  const questionRelatedEvents = useQuestionStore(state => state.questionRelatedEvents)
  const priceHistoryInterval = useQuestionStore(state => state.priceHistoryInterval)
  const setPriceHistoryInterval = useQuestionStore(state => state.setPriceHistoryInterval)
  const previewQuestions = useQuestionStore(state => state.previewQuestions)
  const setPreviewQuestions = useQuestionStore(state => state.setPreviewQuestions)
  const previewSourceTab = useQuestionStore(state => state.previewSourceTab)
  const setPreviewSourceTab = useQuestionStore(state => state.setPreviewSourceTab)
  const previewSource = useQuestionStore(state => state.previewSource)
  const setPreviewSource = useQuestionStore(state => state.setPreviewSource)

  // UI store
  const leftPanelTab = useUIStore(state => state.leftPanelTab)
  const setLeftPanelTab = useUIStore(state => state.setLeftPanelTab)
  const currentDatabasePath = useUIStore(state => state.currentDatabasePath)

  // Custom Hooks
  const {
    questions,
    statistics,
    loadGraph,
    handleFilterChange,
    handleDatabaseChange,
    handleJobComplete,
    handleQuestionsAdded,
    handleQuestionUpdated,
    removeQuestion
  } = useAppData()

  const {
    handleShowNeighborhood,
    handleQuestionFilter
  } = useGraphTraversal(questions)

  // Handle node selection
  const handleNodeClick = useCallback((node) => {
    setSelectedNode(node)
  }, [setSelectedNode])

  // Handle time range change from timeline (client-side filtering)
  const handleTimeRangeChange = useCallback((startDate, endDate) => {
    // Just update the filter state - do NOT mutate graphData
    // The visualization component will handle hiding nodes based on this state
    setTimeFilter(startDate && endDate ? { start: startDate, end: endDate } : null)
  }, [setTimeFilter])

  // Handle question deleted
  const handleQuestionDeleted = useCallback((questionId) => {
    removeQuestion(questionId)
    // Clear selection if deleted question was selected
    if (selectedQuestionId === questionId) {
      setSelectedQuestionId(null)
      handleQuestionFilter(null)
    }
  }, [selectedQuestionId, handleQuestionFilter, removeQuestion, setSelectedQuestionId])

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>WorldReasoner</h1>
          <div className="header-info-bar">
            <DatabaseDropdown onDatabaseChange={handleDatabaseChange} />
            {statistics && (
              <>
                <div className="header-divider"></div>
                <div className="stats-bar">
                  <span>{statistics.total_nodes} events</span>
                  <span>{statistics.total_edges} causal links</span>
                  <span>Avg degree: {statistics.average_out_degree?.toFixed(2)}</span>
                </div>
              </>
            )}
          </div>
        </div>
        <div className="header-right">
        </div>
      </header>

<div className="app-content">
        {/* Top navigation tabs */}
        <div className="top-tabs">
          <button
            className={`top-tab-btn ${leftPanelTab === 'eventgraphs' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('eventgraphs')}
          >
            📊 Event Graphs
          </button>
          <button
            className={`top-tab-btn ${leftPanelTab === 'collection' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('collection')}
          >
            🔍 Collection
          </button>
          <button
            className={`top-tab-btn ${leftPanelTab === 'pipelines' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('pipelines')}
          >
            🔬 Evidence
          </button>

          <button
            className={`top-tab-btn ${leftPanelTab === 'forecast' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('forecast')}
          >
            🎯 Forecast
          </button>
          <button
            className={`top-tab-btn ${leftPanelTab === 'benchmark' ? 'active' : ''}`}
            onClick={() => setLeftPanelTab('benchmark')}
          >
            📈 Benchmark
          </button>
        </div>

        <Suspense fallback={<div className="loading-fallback">Loading...</div>}>
          {leftPanelTab === 'eventgraphs' ? (
            /* Event Graphs page with nested tabs */
            <EventGraphsPage
              fullGraphData={fullGraphData}
              graphData={graphData}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
              loading={loading}
              error={error}
              filters={filters}
              onFilterChange={handleFilterChange}
              onRefresh={() => loadGraph(filters)}
              questions={questions}
              selectedQuestionId={selectedQuestionId}
              onQuestionFilter={(questionId) => {
                setSelectedQuestionId(questionId)
                handleQuestionFilter(questionId)
              }}
              onShowNeighborhood={handleShowNeighborhood}
              onTimeRangeChange={handleTimeRangeChange}
              priceHistoryData={priceHistoryData}
              loadingPriceHistory={loadingPriceHistory}
              questionRelatedEvents={questionRelatedEvents}
              priceHistoryInterval={priceHistoryInterval}
              setPriceHistoryInterval={setPriceHistoryInterval}
              onQuestionUpdated={handleQuestionUpdated}
              onQuestionDeleted={handleQuestionDeleted}
              timeFilter={timeFilter}
            />
          ) : leftPanelTab === 'collection' ? (
            /* Full-width collection page */
            <QuestionCollectionPage
              onQuestionsAdded={handleQuestionsAdded}
              previewQuestions={previewQuestions}
              setPreviewQuestions={setPreviewQuestions}
              sourceTab={previewSourceTab}
              setSourceTab={setPreviewSourceTab}
              previewSource={previewSource}
              setPreviewSource={setPreviewSource}
            />
          ) : leftPanelTab === 'forecast' ? (
            /* Full-width forecast page */
            <ForecastPage />
          ) : leftPanelTab === 'benchmark' ? (
            /* Full-width benchmark page */
            <BenchmarkPage />
          ) : leftPanelTab === 'pipelines' ? (
            /* Full-width pipeline page */
            <PipelinePage
              questions={questions}
              onJobComplete={handleJobComplete}
              databasePath={currentDatabasePath}
            />
          ) : null}
        </Suspense>
      </div>
    </div>
  )
}

export default App
