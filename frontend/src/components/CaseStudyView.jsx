import React from 'react'
import { useCaseStudyData } from '../hooks/useCaseStudyData'
import { useQuestionPriceHistory } from '../hooks/queries/useQuestionQueries'
import { CausalEventsTable } from './CaseStudyView/CausalEventsTable'
import { CausalPressureChart } from './CaseStudyView/CausalPressureChart'
import { InformationStream } from './CaseStudyView/InformationStream'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './CaseStudyView.css'

function CaseStudyView({ graphData, selectedQuestion }) {
  const {
    articles,
    events,
    impacts,
    articleMap,
    groundTruthScenario,
    loadingArticles,
    loadingImpacts
  } = useCaseStudyData(selectedQuestion, graphData)

  const { data: priceHistoryData } = useQuestionPriceHistory(selectedQuestion?.id)

  const hasExplanation = !!selectedQuestion?.causal_explanation
  const hasCausal = Object.keys(impacts).length > 0

  if (!selectedQuestion) {
    return <div className="cs-empty">Select a question to open its case study.</div>
  }

  return (
    <div className="case-study-view">
      {hasExplanation && (
        <section className="cs-section cs-section-panel">
          <div className="cs-readable">
            <h3 className="cs-section-title">Causal Explanation</h3>
            <p className="cs-section-subtitle">Auto-generated explanation of the causal dynamics.</p>
            <div className="cs-impact-details markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {selectedQuestion.causal_explanation}
              </ReactMarkdown>
            </div>
          </div>
        </section>
      )}

      <section className="cs-section cs-section-panel">
        <h3 className="cs-section-title">Causal Events</h3>
        <p className="cs-section-subtitle">Chronological progression of extracted events.</p>
        {(loadingArticles || loadingImpacts) ? (
          <div className="cs-empty">Loading evidence data...</div>
        ) : (
          <CausalEventsTable
            events={events}
            impacts={impacts}
            articleMap={articleMap}
            groundTruthScenario={groundTruthScenario}
            questionId={selectedQuestion?.id}
            showHeader={false}
          />
        )}
      </section>

      {hasCausal && (
        <section className="cs-section cs-section-panel">
          <h3 className="cs-section-title">Evidence Accumulation</h3>
          <p className="cs-section-subtitle">
            Cumulative causal pressure toward the resolved outcome; each step is one event.
          </p>
          {(loadingArticles || loadingImpacts) ? (
            <div className="cs-empty">Loading evidence data...</div>
          ) : (
            <CausalPressureChart
              events={events}
              impacts={impacts}
              groundTruthScenario={groundTruthScenario}
              resolutionDate={selectedQuestion?.resolution_date}
              priceHistory={priceHistoryData?.price_history || null}
              priceOutcomes={priceHistoryData?.token_outcomes || priceHistoryData?.outcomes || null}
            />
          )}
        </section>
      )}

      <section className="cs-section cs-section-panel">
        <div className="cs-readable">
          <h3 className="cs-section-title">Appendix: Information Stream</h3>
          <p className="cs-section-subtitle">Articles collected chronologically.</p>
        </div>
        {(loadingArticles || loadingImpacts) ? (
          <div className="cs-empty">Loading evidence data...</div>
        ) : (
          <InformationStream articles={articles} showHeader={false} />
        )}
      </section>
    </div>
  )
}

export default CaseStudyView
