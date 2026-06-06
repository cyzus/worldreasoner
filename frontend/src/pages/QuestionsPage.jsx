import React from 'react'
import QuestionList from '../components/QuestionList'
import QuestionDetailPanel from '../components/question/QuestionDetailPanel'
import { useQuestionStore } from '../stores/questionStore'
import './QuestionsPage.css'

const QuestionsPage = ({
  // graph data (passed to detail panel tabs)
  graphData,
  selectedNode,
  onNodeClick,
  loading,
  error,
  onShowNeighborhood,
  timeFilter,
  // question callbacks
  questions,
  onQuestionSelect,
  onQuestionUpdated,
  onQuestionDeleted,
  // price history (passed through to detail panel)
  priceHistoryData,
  loadingPriceHistory,
  questionRelatedEvents,
  priceHistoryInterval,
  setPriceHistoryInterval,
}) => {
  const selectedQuestionId = useQuestionStore(state => state.selectedQuestionId)
  const setSelectedQuestionId = useQuestionStore(state => state.setSelectedQuestion)

  const handleQuestionSelect = (questionId) => {
    setSelectedQuestionId(questionId)
    onQuestionSelect?.(questionId)
  }

  const selectedQuestion = questions.find(q => q.id === selectedQuestionId) ?? null

  return (
    <div className="questions-page">
      {/* Left: question list sidebar */}
      <aside className="questions-sidebar">
        <QuestionList
          questions={questions}
          selectedQuestionId={selectedQuestionId}
          statusFilterVariant="eventgraph"
          onQuestionSelect={handleQuestionSelect}
          onClose={() => {}}
          onQuestionUpdated={onQuestionUpdated}
          onQuestionDeleted={onQuestionDeleted}
        />
      </aside>

      {/* Right: detail panel */}
      <main className="questions-main">
        {selectedQuestion ? (
          <QuestionDetailPanel
            question={selectedQuestion}
            graphData={graphData}
            selectedNode={selectedNode}
            onNodeClick={onNodeClick}
            loading={loading}
            error={error}
            onShowNeighborhood={onShowNeighborhood}
            timeFilter={timeFilter}
            priceHistoryData={priceHistoryData}
            loadingPriceHistory={loadingPriceHistory}
            questionRelatedEvents={questionRelatedEvents}
            priceHistoryInterval={priceHistoryInterval}
            setPriceHistoryInterval={setPriceHistoryInterval}
          />
        ) : (
          <div className="questions-empty">
            <div className="questions-empty-icon">👈</div>
            <h3>Select a question</h3>
            <p>Choose a question from the sidebar to view its evidence, graph, and forecasts.</p>
          </div>
        )}
      </main>
    </div>
  )
}

export default QuestionsPage
