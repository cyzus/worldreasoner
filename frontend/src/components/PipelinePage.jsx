import React, { useState, useEffect } from 'react'
import QuestionList from './QuestionList'
import PipelineControl from './PipelineControl'
import './PipelinePage.css'

const PipelinePage = ({ questions, onJobComplete }) => {
  const [selectedQuestions, setSelectedQuestions] = useState([])
  const [jobs, setJobs] = useState([])
  const [loadingJobs, setLoadingJobs] = useState(false)
  const [selectedJob, setSelectedJob] = useState(null)
  const [jobDetails, setJobDetails] = useState(null)
  const [loadingDetails, setLoadingDetails] = useState(false)

  // Load recent jobs
  const loadJobs = async () => {
    setLoadingJobs(true)
    try {
      const response = await fetch('http://localhost:8018/api/pipelines/jobs?limit=10')
      const data = await response.json()
      setJobs(data)
    } catch (error) {
      console.error('Failed to load jobs:', error)
    } finally {
      setLoadingJobs(false)
    }
  }

  useEffect(() => {
    loadJobs()
    // Refresh jobs every 5 seconds
    const interval = setInterval(loadJobs, 5000)
    return () => clearInterval(interval)
  }, [])

  const handleJobComplete = (results) => {
    onJobComplete?.(results)
    loadJobs() // Refresh job list
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'running': return '#2196f3'
      case 'completed': return '#4caf50'
      case 'failed': return '#f44336'
      case 'cancelled': return '#ff9800'
      default: return '#9e9e9e'
    }
  }

  const getStatusIcon = (status) => {
    switch (status) {
      case 'running': return '⏳'
      case 'completed': return '✅'
      case 'failed': return '❌'
      case 'cancelled': return '⚠️'
      default: return '⏸️'
    }
  }

  const formatDate = (dateString) => {
    const date = new Date(dateString)
    const now = new Date()
    const diffMs = now - date
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins}m ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}d ago`
  }

  const handleJobClick = async (job) => {
    setSelectedJob(job.job_id)
    setLoadingDetails(true)
    try {
      // Fetch full job details including results
      const response = await fetch(`http://localhost:8018/api/pipelines/jobs/${job.job_id}`)
      const data = await response.json()
      setJobDetails(data)
    } catch (error) {
      console.error('Failed to load job details:', error)
      setJobDetails(null)
    } finally {
      setLoadingDetails(false)
    }
  }

  return (
    <div className="pipeline-page page-container">
      <div className="pipeline-page-header page-header">
        <h2>Evidence Collection</h2>
      </div>

      <div className="page-content">
        {/* Left Sidebar: Pipeline Controls + Jobs */}
        <div className="page-sidebar">
          <div className="scroll-container">
            {/* Pipeline Controls */}
            <div className="section-card">
              <PipelineControl
                selectedQuestions={selectedQuestions}
                onJobComplete={handleJobComplete}
              />
            </div>

            {/* Job History */}
            <div className="section-card">
              <div className="section-header">
                <h3>Recent Jobs</h3>
                <button
                  className="refresh-btn"
                  onClick={loadJobs}
                  disabled={loadingJobs}
                >
                  🔄 {loadingJobs ? 'Loading...' : 'Refresh'}
                </button>
              </div>

              <div className="jobs-list">
                {jobs.length === 0 ? (
                  <div className="jobs-empty">
                    <div className="jobs-empty-icon">📋</div>
                    <div>No recent jobs</div>
                    <div style={{ fontSize: '12px', color: '#999', marginTop: '4px' }}>
                      Start a pipeline to see jobs here
                    </div>
                  </div>
                ) : (
                  jobs.map(job => (
                    <div
                      key={job.job_id}
                      className={`job-item ${selectedJob === job.job_id ? 'selected' : ''}`}
                      onClick={() => handleJobClick(job)}
                      style={{ cursor: 'pointer' }}
                    >
                      <div className="job-header">
                        <div className="job-info">
                          <span
                            className="job-status-icon"
                            style={{ color: getStatusColor(job.status) }}
                          >
                            {getStatusIcon(job.status)}
                          </span>
                          <span className="job-id">{job.job_id}</span>
                          <span className="job-type-badge">{job.pipeline_type || 'N/A'}</span>
                        </div>
                        <span className="job-time">{formatDate(job.created_at)}</span>
                      </div>

                      {job.status === 'running' && (
                        <div className="job-progress">
                          <div className="job-progress-bar-container">
                            <div
                              className="job-progress-bar"
                              style={{
                                width: `${(job.progress || 0) * 100}%`,
                                backgroundColor: getStatusColor(job.status)
                              }}
                            />
                          </div>
                          <div className="job-progress-text">
                            {job.processed_count || 0} / {job.total_count || 0} questions
                          </div>
                        </div>
                      )}

                      {job.status === 'completed' && job.results && (
                        <div className="job-results">
                          <span className="result-stat success">
                            ✓ {job.results.processed || 0} processed
                          </span>
                          {job.results.failed > 0 && (
                            <span className="result-stat failed">
                              ✗ {job.results.failed} failed
                            </span>
                          )}
                          {job.results.skipped > 0 && (
                            <span className="result-stat skipped">
                              ⊘ {job.results.skipped} skipped
                            </span>
                          )}
                          {job.results.duration_seconds && (
                            <span className="result-stat duration">
                              ⏱ {job.results.duration_seconds.toFixed(1)}s
                            </span>
                          )}
                        </div>
                      )}

                      {job.status === 'failed' && (
                        <div className="job-error">
                          <div style={{ fontWeight: 600, marginBottom: '4px' }}>
                            {job.message || 'Pipeline failed'}
                          </div>
                          {job.results?.failed_details && job.results.failed_details.length > 0 && (
                            <div style={{ marginTop: '8px' }}>
                              {job.results.failed_details.map((item, idx) => (
                                <div key={idx} style={{ fontSize: '11px', marginTop: '4px' }}>
                                  • <span style={{ fontFamily: 'monospace' }}>{item.id}</span>: {item.error}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}

                      {job.message && job.status === 'running' && (
                        <div className="job-message">
                          {job.message}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Right Main Content: Question Selection or Job Details */}
        <div className="page-main">
          <div className="scroll-container">
            {selectedJob && jobDetails ? (
              <div className="job-details-section">
                <div className="section-header">
                  <h3>Job Details: {selectedJob}</h3>
                  <button
                    className="close-btn"
                    onClick={() => { setSelectedJob(null); setJobDetails(null); }}
                  >
                    ✕ Close
                  </button>
                </div>

                <div className="job-details-content">
                  <div className="job-detail-card">
                    <h4>Status</h4>
                    <div className="job-detail-row">
                      <span className="label">Status:</span>
                      <span className="value" style={{ color: getStatusColor(jobDetails.status) }}>
                        {getStatusIcon(jobDetails.status)} {jobDetails.status}
                      </span>
                    </div>
                    <div className="job-detail-row">
                      <span className="label">Pipeline Type:</span>
                      <span className="value">{jobDetails.pipeline_type}</span>
                    </div>
                    <div className="job-detail-row">
                      <span className="label">Progress:</span>
                      <span className="value">{(jobDetails.progress * 100).toFixed(0)}%</span>
                    </div>
                    <div className="job-detail-row">
                      <span className="label">Created:</span>
                      <span className="value">{new Date(jobDetails.created_at).toLocaleString()}</span>
                    </div>
                    <div className="job-detail-row">
                      <span className="label">Updated:</span>
                      <span className="value">{new Date(jobDetails.updated_at).toLocaleString()}</span>
                    </div>
                    {jobDetails.message && (
                      <div className="job-detail-row">
                        <span className="label">Message:</span>
                        <span className="value">{jobDetails.message}</span>
                      </div>
                    )}
                  </div>

                  {jobDetails.results && Object.keys(jobDetails.results).length > 0 && (
                    <div className="job-detail-card">
                      <h4>Results</h4>

                      {/* Summary */}
                      <div className="results-summary">
                        {jobDetails.results.processed !== undefined && (
                          <div className="result-stat-large success">
                            <div className="stat-value">{jobDetails.results.processed}</div>
                            <div className="stat-label">Processed</div>
                          </div>
                        )}
                        {jobDetails.results.failed !== undefined && jobDetails.results.failed > 0 && (
                          <div className="result-stat-large failed">
                            <div className="stat-value">{jobDetails.results.failed}</div>
                            <div className="stat-label">Failed</div>
                          </div>
                        )}
                        {jobDetails.results.skipped !== undefined && jobDetails.results.skipped > 0 && (
                          <div className="result-stat-large skipped">
                            <div className="stat-value">{jobDetails.results.skipped}</div>
                            <div className="stat-label">Skipped</div>
                          </div>
                        )}
                        {jobDetails.results.duration_seconds && (
                          <div className="result-stat-large duration">
                            <div className="stat-value">{jobDetails.results.duration_seconds.toFixed(1)}s</div>
                            <div className="stat-label">Duration</div>
                          </div>
                        )}
                      </div>

                      {/* Processed Questions */}
                      {jobDetails.results.processed_details && jobDetails.results.processed_details.length > 0 && (
                        <div className="result-details-section">
                          <h5>✓ Processed Questions ({jobDetails.results.processed_details.length})</h5>
                          <div className="result-items">
                            {jobDetails.results.processed_details.map((item, idx) => (
                              <div key={idx} className="result-item success">
                                <code>{typeof item === 'string' ? item : item.id}</code>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Failed Questions */}
                      {jobDetails.results.failed_details && jobDetails.results.failed_details.length > 0 && (
                        <div className="result-details-section">
                          <h5>✗ Failed Questions ({jobDetails.results.failed_details.length})</h5>
                          <div className="result-items">
                            {jobDetails.results.failed_details.map((item, idx) => (
                              <div key={idx} className="result-item failed">
                                <code>{item.id}</code>
                                {item.error && <div className="error-message">{item.error}</div>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Skipped Questions */}
                      {jobDetails.results.skipped_details && jobDetails.results.skipped_details.length > 0 && (
                        <div className="result-details-section">
                          <h5>⊘ Skipped Questions ({jobDetails.results.skipped_details.length})</h5>
                          <div className="result-items">
                            {jobDetails.results.skipped_details.map((item, idx) => (
                              <div key={idx} className="result-item skipped">
                                <code>{typeof item === 'string' ? item : item.id}</code>
                                {item.reason && <div className="skip-reason">{item.reason}</div>}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ) : loadingDetails ? (
              <div className="loading-details">
                <div className="loading-spinner"></div>
                <div>Loading job details...</div>
              </div>
            ) : (
              <div className="pipeline-questions-section">
                <div className="section-header">
                  <h3>Select Questions</h3>
                  <span className="selected-badge">
                    {selectedQuestions.length} selected
                  </span>
                </div>
                <QuestionList
                  questions={questions}
                  selectedQuestionId={null}
                  onQuestionSelect={() => { }} // Disabled in pipeline mode
                  multiSelectMode={true}
                  onQuestionsSelected={setSelectedQuestions}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default PipelinePage
