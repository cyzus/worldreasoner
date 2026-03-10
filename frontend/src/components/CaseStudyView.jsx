import React, { useState } from 'react'
import { useCaseStudyData } from '../hooks/useCaseStudyData'
import { useForecastGraph } from '../hooks/queries/useQuestionQueries'
import { ForecastComparison } from './CaseStudyView/ForecastComparison'
import { CausalEventsTable } from './CaseStudyView/CausalEventsTable'
import { InformationStream } from './CaseStudyView/InformationStream'
import { ForecastGraphModal } from './CaseStudyView/ForecastGraphModal'
import ReactMarkdown from 'react-markdown'
import './CaseStudyView.css'

/**
 * CaseStudyView - Displays a clean, chronological view of articles and events
 * bypassing the heavy force-directed graph. Also handles forecast comparison.
 */
function CaseStudyView({
  graphData,
  forecasts,
  selectedQuestion
}) {
  const [activeForecastId, setActiveForecastId] = useState(null)

  // Use our custom hook to fetch and memoize data
  const {
    articles,
    events,
    impacts,
    articleMap,
    groundTruthScenario,
    loadingArticles,
    loadingImpacts
  } = useCaseStudyData(selectedQuestion, graphData)

  // Use React Query for the modal data loading (enabled only when an ID is active)
  const {
    data: activeForecastGraph,
    isFetching: loadingGraph
  } = useForecastGraph(activeForecastId)

  const handleViewForecastGraph = (forecastId) => {
    setActiveForecastId(forecastId)
  }

  const handleCloseForecastGraph = () => {
    setActiveForecastId(null)
  }

  // Show a loading state if data is being fetched
  if (loadingArticles || loadingImpacts) {
    return (
      <div className="case-study-view" style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
        <p>Loading case study data...</p>
      </div>
    )
  }

  return (
    <div className="case-study-view">
      <ForecastComparison
        selectedQuestion={selectedQuestion}
        forecasts={forecasts}
        onViewForecastGraph={handleViewForecastGraph}
        loadingGraph={loadingGraph}
      />

      {selectedQuestion?.causal_explanation && (
        <div className="cs-section">
          <h3 className="cs-section-title">💡 Causal Explanation</h3>
          <p className="cs-section-subtitle">Auto-generated explanation of the causal dynamics</p>
          <div className="cs-impact-details markdown-body" style={{ marginTop: 0 }}>
            <ReactMarkdown>{selectedQuestion.causal_explanation}</ReactMarkdown>
          </div>
        </div>
      )}

      <CausalEventsTable
        events={events}
        impacts={impacts}
        articleMap={articleMap}
        groundTruthScenario={groundTruthScenario}
      />

      <InformationStream
        articles={articles}
      />

      <ForecastGraphModal
        activeForecastGraph={activeForecastGraph}
        onClose={handleCloseForecastGraph}
      />
    </div>
  )
}

export default CaseStudyView
