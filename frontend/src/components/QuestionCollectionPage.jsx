import React from 'react'
import CollectionConfigPanel from './CollectionConfigPanel'
import QuestionPreviewList from './QuestionPreviewList'
import ManualQuestionForm from './ManualQuestionForm'
import { JobSidebar, JobDetails } from './JobManager'
import { useQuestionCollection } from '../hooks/useQuestionCollection'
import './QuestionCollectionPage.css'

/**
 * QuestionCollectionPage - Full-width page for collecting questions
 */
function QuestionCollectionPage({
  onQuestionsAdded,
  previewQuestions = [],
  setPreviewQuestions = () => { },
  sourceTab = 'polymarket',
  setSourceTab = () => { },
  previewSource = null,
  setPreviewSource = () => { }
}) {
  const {
    loading,
    error,
    success,
    setError,
    setSuccess,
    filteredPreviewQuestions,
    handleFetchPreview,
    handleManualQuestionCreated,
    handleSaveSelected,
    jobs,
    loadingJobs,
    selectedJobId,
    jobDetails,
    loadingDetails,
    selectJob,
    loadJobs
  } = useQuestionCollection({
    onQuestionsAdded,
    previewQuestions,
    setPreviewQuestions,
    sourceTab,
    previewSource,
    setPreviewSource
  })

  return (
    <div className="collection-page page-container">
      {/* Source tabs */}
      <div className="source-tabs">
        <button
          className={`source-tab ${sourceTab === 'polymarket' ? 'active' : ''}`}
          onClick={() => {
            setSourceTab('polymarket')
            setError(null)
            setSuccess(null)
          }}
        >
          📊 Polymarket
        </button>
        <button
          className={`source-tab ${sourceTab === 'news' ? 'active' : ''}`}
          onClick={() => {
            setSourceTab('news')
            setError(null)
            setSuccess(null)
          }}
        >
          📰 News
        </button>
        <button
          className={`source-tab ${sourceTab === 'manual' ? 'active' : ''}`}
          onClick={() => {
            setSourceTab('manual')
            setError(null)
            setSuccess(null)
          }}
        >
          ✏️ Manual
        </button>
      </div>

      {/* Manual tab shows form, other tabs show collection interface */}
      <div className="page-content">
        {sourceTab === 'manual' ? (
          <div className="page-main">
            <div className="scroll-container">
              <ManualQuestionForm onQuestionCreated={handleManualQuestionCreated} />
            </div>
          </div>
        ) : (
          <>
            {/* Left panel: Configuration */}
            <div className="page-sidebar">
              <div className="scroll-container">
                <CollectionConfigPanel
                  source={sourceTab}
                  onFetch={handleFetchPreview}
                  loading={loading}
                />

                {/* Job History */}
                <div style={{ marginTop: '16px' }}>
                  <JobSidebar
                    jobs={jobs}
                    selectedJobId={selectedJobId}
                    onJobClick={(job) => selectJob(job.job_id)}
                    loading={loadingJobs}
                    onRefresh={loadJobs}
                    title="Recent Collection Jobs"
                  />
                </div>
              </div>
            </div>

            {/* Right panel: Preview and selection or Job Details */}
            <div className="page-main">
              <div className="scroll-container">
                {selectedJobId && jobDetails ? (
                  <JobDetails
                    job={jobDetails}
                    onClose={() => selectJob(null)}
                  />
                ) : loadingDetails ? (
                  <div className="loading-details">
                    <div className="loading-spinner"></div>
                    <div>Loading job details...</div>
                  </div>
                ) : (
                  <QuestionPreviewList
                    questions={filteredPreviewQuestions}
                    onSaveSelected={handleSaveSelected}
                    loading={loading}
                    source={sourceTab}
                  />
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default QuestionCollectionPage
