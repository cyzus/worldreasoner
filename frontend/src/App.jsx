import React, { Suspense, useCallback, lazy } from 'react'
import DatabaseDropdown from './components/DatabaseDropdown'
import { useGraphStore } from './stores/graphStore'
import { useQuestionStore } from './stores/questionStore'
import { useUIStore } from './stores/uiStore'
import { useGraphTraversal } from './hooks/useGraphTraversal'
import { useAppData } from './hooks/useAppData'
import './App.css'

const QuestionsPage = lazy(() => import('./pages/QuestionsPage'))
const DataPage = lazy(() => import('./pages/DataPage'))
const BenchmarkPage = lazy(() => import('./components/BenchmarkPage'))

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

  const {
    questions,
    statistics,
    loadGraph,
    handleFilterChange,
    handleDatabaseChange,
    handleJobComplete,
    handleQuestionsAdded,
    handleQuestionUpdated,
    removeQuestion,
  } = useAppData()

  const { handleShowNeighborhood, handleQuestionFilter } = useGraphTraversal(questions)

  const handleNodeClick = useCallback((node) => {
    setSelectedNode(node)
  }, [setSelectedNode])

  const handleTimeRangeChange = useCallback((startDate, endDate) => {
    setTimeFilter(startDate && endDate ? { start: startDate, end: endDate } : null)
  }, [setTimeFilter])

  const handleQuestionDeleted = useCallback((questionId) => {
    removeQuestion(questionId)
    if (selectedQuestionId === questionId) {
      setSelectedQuestionId(null)
      handleQuestionFilter(null)
    }
  }, [selectedQuestionId, handleQuestionFilter, removeQuestion, setSelectedQuestionId])

  const handleQuestionSelect = useCallback((questionId) => {
    setSelectedQuestionId(questionId)
    handleQuestionFilter(questionId)
  }, [setSelectedQuestionId, handleQuestionFilter])

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <h1>WorldReasoner</h1>
          <DatabaseDropdown onDatabaseChange={handleDatabaseChange} />
          <div className="header-divider"></div>
          <nav className="top-tabs">
            <button
              className={`top-tab-btn ${leftPanelTab === 'questions' ? 'active' : ''}`}
              onClick={() => setLeftPanelTab('questions')}
            >
              Questions
            </button>
            <button
              className={`top-tab-btn ${leftPanelTab === 'data' ? 'active' : ''}`}
              onClick={() => setLeftPanelTab('data')}
            >
              Data
            </button>
            <button
              className={`top-tab-btn ${leftPanelTab === 'benchmark' ? 'active' : ''}`}
              onClick={() => setLeftPanelTab('benchmark')}
            >
              Benchmark
            </button>
          </nav>
        </div>
        <div className="stats-bar">
          <span>{questions.length} questions</span>
          {statistics && (
            <>
              <span>{statistics.total_nodes} events</span>
              <span>{statistics.total_articles ?? 0} articles</span>
            </>
          )}
        </div>
      </header>

      <div className="app-content">
        <Suspense fallback={<div className="loading-fallback">Loading...</div>}>
          {leftPanelTab === 'questions' ? (
            <QuestionsPage
              graphData={graphData}
              selectedNode={selectedNode}
              onNodeClick={handleNodeClick}
              loading={loading}
              error={error}
              questions={questions}
              onQuestionSelect={handleQuestionSelect}
              onShowNeighborhood={handleShowNeighborhood}
              timeFilter={timeFilter}
              priceHistoryData={priceHistoryData}
              loadingPriceHistory={loadingPriceHistory}
              questionRelatedEvents={questionRelatedEvents}
              priceHistoryInterval={priceHistoryInterval}
              setPriceHistoryInterval={setPriceHistoryInterval}
              onQuestionUpdated={handleQuestionUpdated}
              onQuestionDeleted={handleQuestionDeleted}
            />
          ) : leftPanelTab === 'data' ? (
            <DataPage
              onQuestionsAdded={handleQuestionsAdded}
              previewQuestions={previewQuestions}
              setPreviewQuestions={setPreviewQuestions}
              sourceTab={previewSourceTab}
              setSourceTab={setPreviewSourceTab}
              previewSource={previewSource}
              setPreviewSource={setPreviewSource}
              questions={questions}
              onJobComplete={handleJobComplete}
              databasePath={currentDatabasePath}
            />
          ) : leftPanelTab === 'benchmark' ? (
            <BenchmarkPage />
          ) : null}
        </Suspense>
      </div>
    </div>
  )
}

export default App
