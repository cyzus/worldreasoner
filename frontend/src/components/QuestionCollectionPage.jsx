import React, { useState, useCallback } from 'react'
import CollectionConfigPanel from './CollectionConfigPanel'
import QuestionPreviewList from './QuestionPreviewList'
import ManualQuestionForm from './ManualQuestionForm'
import { JobSidebar, JobDetails } from './JobManager'
import { usePipelineJobs } from '../hooks/usePipelineJobs'
import './QuestionCollectionPage.css'

/**
 * QuestionCollectionPage - Full-width page for collecting questions from various sources
 *
 * Features:
 * - Source selection (Polymarket, News, Manual)
 * - Configuration panel for filtering and collection parameters
 * - Preview list with manual selection
 * - Manual question creation form
 * - Batch save to database
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
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  // Job management
  const {
    jobs,
    loadingJobs,
    selectedJobId,
    jobDetails,
    loadingDetails,
    selectJob,
    loadJobs
  } = usePipelineJobs(null); // Remove filter to see all jobs including news collection

  // Log when preview questions change (for debugging)
  React.useEffect(() => {
    console.log(`[QuestionCollectionPage] Preview: ${previewQuestions.length} questions from ${previewSource}, current tab: ${sourceTab}`)
  }, [previewQuestions, previewSource, sourceTab])

  // Only show preview questions if they match the current source tab
  const filteredPreviewQuestions = React.useMemo(() => {
    // If no preview source, show nothing (fresh state)
    if (!previewSource) {
      return []
    }
    // If preview source matches current tab, show the questions
    if (previewSource === sourceTab) {
      return previewQuestions
    }
    // Otherwise, don't show questions from a different source
    return []
  }, [previewQuestions, previewSource, sourceTab])

  /**
   * Handle fetching preview questions from the API
   */
  const handleFetchPreview = useCallback(async (config) => {
    console.log('[QuestionCollectionPage] Fetching preview with config:', config, 'source:', sourceTab)

    setLoading(true)
    setError(null)
    setSuccess(null)
    setPreviewQuestions([]) // Clear preview questions when starting a new fetch
    setPreviewSource(null) // Clear preview source

    try {
      // Branch logic: For News (slow), start a background job. For Polymarket (fast), use preview.
      if (sourceTab === 'news') {
        const response = await fetch('http://localhost:8018/api/pipelines/jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            question_ids: [], // Not needed for collection
            pipeline_type: 'news_collection',
            config: config
          })
        });

        if (!response.ok) throw new Error('Failed to start news collection job');

        const data = await response.json();
        setSuccess(`Started News Collection Job: ${data.job_id}`);

        // Refresh jobs and select
        await loadJobs();
        selectJob(data.job_id);

      } else {
        // Existing Preview Logic for Polymarket
        const requestBody = {
          source: sourceTab,
          ...config,
        }

        console.log('[QuestionCollectionPage] Request body:', JSON.stringify(requestBody, null, 2))

        const response = await fetch('http://localhost:8018/api/questions/preview', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        })

        if (!response.ok) {
          const errorData = await response.json()
          throw new Error(errorData.detail || 'Failed to fetch questions')
        }

        const data = await response.json()

        if (data.success) {
          setPreviewQuestions(data.questions)
          setPreviewSource(data.source) // Store which source these questions came from
          setSuccess(`Fetched ${data.total} questions from ${data.source}`)
        } else {
          setError(data.errors.join('; ') || 'Failed to fetch questions')
        }
      }
    } catch (err) {
      setError(`Error: ${err.message}`)
      console.error('Preview/Job fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [sourceTab, setPreviewQuestions, setPreviewSource, loadJobs, selectJob])

  /**
   * Handle manual question creation
   */
  const handleManualQuestionCreated = useCallback((question) => {
    setSuccess(`Question created: ${question.id}`)

    // Notify parent if callback provided
    if (onQuestionsAdded) {
      onQuestionsAdded(1)
    }
  }, [onQuestionsAdded])

  /**
   * Handle saving selected questions to database
   */
  const handleSaveSelected = useCallback(async (selectedQuestions) => {
    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await fetch('http://localhost:8018/api/questions/batch-save', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question_ids: selectedQuestions.map(q => q.id),
          questions: selectedQuestions,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to save questions')
      }

      const data = await response.json()

      if (data.success) {
        setSuccess(
          `✓ Saved ${data.saved_count} questions${data.skipped_count > 0 ? ` (${data.skipped_count} duplicates skipped)` : ''}`
        )

        // Remove saved questions from preview
        const savedIds = new Set(selectedQuestions.map(q => q.id))
        setPreviewQuestions(prev => prev.filter(q => !savedIds.has(q.id)))

        // Notify parent if callback provided
        if (onQuestionsAdded) {
          onQuestionsAdded(data.saved_count)
        }
      } else {
        setError(data.errors?.join('; ') || 'Failed to save questions')
      }
    } catch (err) {
      setError(`Error: ${err.message}`)
      console.error('Batch save error:', err)
    } finally {
      setLoading(false)
    }
  }, [onQuestionsAdded, setPreviewQuestions])

  return (
    <div className="collection-page page-container">
      <div className="collection-header">
        <h2>🔍 Question Collection</h2>
        <p className="collection-subtitle">
          Fetch questions from various sources and manually select which ones to add to your database
        </p>
      </div>

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

      {/* Status messages */}
      {error && (
        <div className="message error-message" style={{ margin: '0 20px 12px 20px' }}>
          ⚠️ {error}
        </div>
      )}
      {success && (
        <div className="message success-message" style={{ margin: '0 20px 12px 20px' }}>
          {success}
        </div>
      )}

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
