import React, { useState } from 'react'
import CaseStudyView from '../CaseStudyView'
import QuestionGraphTab from './QuestionGraphTab'
import QuestionForecastTab from './QuestionForecastTab'
import './QuestionDetailPanel.css'

const TABS = [
  { id: 'evidence', label: 'Evidence' },
  { id: 'graph',    label: 'Graph' },
  { id: 'forecast', label: 'Forecast' },
]

const QuestionDetailPanel = ({
  question,
  graphData,
  selectedNode,
  onNodeClick,
  loading,
  error,
  onShowNeighborhood,
  onTimeRangeChange,
  timeFilter,
  priceHistoryData,
  loadingPriceHistory,
  questionRelatedEvents,
  priceHistoryInterval,
  setPriceHistoryInterval,
}) => {
  const [activeTab, setActiveTab] = useState('evidence')

  return (
    <div className="qdp">
      {/* Question header */}
      <div className="qdp-header">
        <div className="qdp-meta">
          <span className="qdp-source">{question.source}</span>
          <span className="qdp-domain">{question.domain}</span>
          {question.ground_truth != null && (
            <span className="qdp-gt">GT: {String(question.ground_truth)}</span>
          )}
          {question.resolution_date && (
            <span className="qdp-date">
              {new Date(question.resolution_date).toLocaleDateString()}
            </span>
          )}
        </div>
        <h2 className="qdp-title">{question.question_text}</h2>
      </div>

      {/* Sub-tab bar */}
      <div className="qdp-tabs">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`qdp-tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="qdp-content">
        {activeTab === 'evidence' && (
          <CaseStudyView
            graphData={graphData}
            selectedQuestion={question}
          />
        )}
        {activeTab === 'graph' && (
          <QuestionGraphTab
            question={question}
            graphData={graphData}
            selectedNode={selectedNode}
            onNodeClick={onNodeClick}
            loading={loading}
            error={error}
            onShowNeighborhood={onShowNeighborhood}
            timeFilter={timeFilter}
          />
        )}
        {activeTab === 'forecast' && (
          <QuestionForecastTab question={question} />
        )}
      </div>
    </div>
  )
}

export default QuestionDetailPanel
