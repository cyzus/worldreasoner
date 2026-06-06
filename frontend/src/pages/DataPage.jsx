import React, { useState, Suspense, lazy } from 'react'
import './DataPage.css'

const QuestionCollectionPage = lazy(() => import('../components/QuestionCollectionPage'))
const PipelinePage = lazy(() => import('../components/PipelinePage'))

const DataPage = ({
  // Collection props
  onQuestionsAdded,
  previewQuestions,
  setPreviewQuestions,
  sourceTab,
  setSourceTab,
  previewSource,
  setPreviewSource,
  // Evidence props
  questions,
  onJobComplete,
  databasePath,
}) => {
  const [activeTab, setActiveTab] = useState('collection')

  return (
    <div className="data-page">
      <div className="data-page-tabs">
        <button
          className={`data-tab-btn ${activeTab === 'collection' ? 'active' : ''}`}
          onClick={() => setActiveTab('collection')}
        >
          Collection
        </button>
        <button
          className={`data-tab-btn ${activeTab === 'evidence' ? 'active' : ''}`}
          onClick={() => setActiveTab('evidence')}
        >
          Evidence
        </button>
      </div>

      <div className="data-page-content">
        <Suspense fallback={<div className="loading-fallback">Loading...</div>}>
          {activeTab === 'collection' ? (
            <QuestionCollectionPage
              onQuestionsAdded={onQuestionsAdded}
              previewQuestions={previewQuestions}
              setPreviewQuestions={setPreviewQuestions}
              sourceTab={sourceTab}
              setSourceTab={setSourceTab}
              previewSource={previewSource}
              setPreviewSource={setPreviewSource}
            />
          ) : (
            <PipelinePage
              questions={questions}
              onJobComplete={onJobComplete}
              databasePath={databasePath}
            />
          )}
        </Suspense>
      </div>
    </div>
  )
}

export default DataPage
