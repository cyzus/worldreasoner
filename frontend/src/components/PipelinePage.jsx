import React, { useState, useEffect } from 'react'
import QuestionList from './QuestionList'
import PipelineControl from './PipelineControl'
import DatabaseSelector from './DatabaseSelector'
import './PipelinePage.css'

const PipelinePage = ({ questions, onJobComplete, onDatabaseChange }) => {
  const [selectedQuestions, setSelectedQuestions] = useState([])
  const [jobs, setJobs] = useState([])
  const [loadingJobs, setLoadingJobs] = useState(false)

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

  const handleDatabaseChange = (dbPath) => {
    // Clear selected questions when database changes
    setSelectedQuestions([])
    // Reload jobs for new database
    loadJobs()
    // Notify parent
    onDatabaseChange?.(dbPath)
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

  return (
    <div className="pipeline-page">
      <div className="pipeline-page-header">
        <h2>Pipeline Operations</h2>
      </div>

      <div className="pipeline-page-content">
        {/* Left: Question Selection */}
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
            onQuestionSelect={() => {}} // Disabled in pipeline mode
            multiSelectMode={true}
            onQuestionsSelected={setSelectedQuestions}
          />
        </div>

        {/* Right: Database + Pipeline Controls & Job History */}
        <div className="pipeline-actions-section">
          {/* Database Selector */}
          <div className="section-card">
            <DatabaseSelector onDatabaseChange={handleDatabaseChange} />
          </div>

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
                  <div key={job.job_id} className="job-item">
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
    </div>
  )
}

export default PipelinePage
