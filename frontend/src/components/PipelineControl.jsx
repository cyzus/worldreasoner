import React, { useState, useEffect } from 'react'
import './PipelineControl.css'

const PipelineControl = ({ selectedQuestions, onJobComplete }) => {
  const [activeJob, setActiveJob] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [error, setError] = useState(null)

  // WebSocket connection for progress updates
  useEffect(() => {
    if (!activeJob) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.hostname
    const port = 8018 // Backend port
    const ws = new WebSocket(
      `${protocol}//${host}:${port}/api/pipelines/jobs/${activeJob}/ws`
    )

    let connected = false

    ws.onopen = () => {
      connected = true
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      setJobStatus(data)

      if (data.status === 'completed') {
        onJobComplete?.(data.results)
        setActiveJob(null)
      } else if (data.status === 'failed') {
        // Build detailed error message
        let errorMsg = data.message || 'Pipeline failed'
        if (data.results?.failed_details && data.results.failed_details.length > 0) {
          errorMsg += '\n\nDetails:\n' + data.results.failed_details
            .map(item => `• ${item.id}: ${item.error}`)
            .join('\n')
        }
        setError(errorMsg)
        setActiveJob(null)
      }
    }

    ws.onerror = (event) => {
      // Only show error if we never connected successfully
      if (!connected) {
        console.error('WebSocket connection error:', event)
        setError('Failed to connect to job progress stream')
      }
    }

    ws.onclose = (event) => {
      // Only show error if connection closed unexpectedly before we got any data
      if (!connected && !event.wasClean) {
        console.error('WebSocket closed unexpectedly:', event)
      }
    }

    return () => ws.close()
  }, [activeJob, onJobComplete])

  const startPipeline = async (pipelineType) => {
    if (!selectedQuestions.length) return

    try {
      setError(null)
      const response = await fetch('http://localhost:8018/api/pipelines/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question_ids: selectedQuestions,
          pipeline_type: pipelineType,
          config: {},
        }),
      })

      if (!response.ok) throw new Error('Failed to start job')

      const job = await response.json()
      setActiveJob(job.job_id)
      setJobStatus(job)
    } catch (err) {
      setError(err.message)
    }
  }

  const cancelJob = async () => {
    if (!activeJob) return

    try {
      await fetch(`http://localhost:8018/api/pipelines/jobs/${activeJob}`, {
        method: 'DELETE',
      })
      setActiveJob(null)
      setJobStatus(null)
    } catch (err) {
      setError(err.message)
    }
  }

  const clearEvidence = async () => {
    if (!selectedQuestions.length) return

    if (!window.confirm(`Clear evidence for ${selectedQuestions.length} questions?`)) {
      return
    }

    try {
      setError(null)
      const response = await fetch('http://localhost:8018/api/pipelines/questions/clear-evidence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question_ids: selectedQuestions,
          cascade: true,
        }),
      })

      const result = await response.json()
      alert(`Cleared evidence for ${result.cleared.length} questions`)
    } catch (err) {
      setError(err.message)
    }
  }

  const isRunning = activeJob && jobStatus?.status === 'running'
  const progress = jobStatus?.progress || 0

  return (
    <div className="pipeline-control">
      <div className="pipeline-header">
        <h3>Pipeline Actions</h3>
        <span className="selected-count">
          {selectedQuestions.length} questions selected
        </span>
      </div>

      {error && (
        <div className="error-message">
          <div style={{ whiteSpace: 'pre-wrap', flex: 1 }}>{error}</div>
          <button onClick={() => setError(null)} className="dismiss-btn">Dismiss</button>
        </div>
      )}

      {isRunning ? (
        <div className="progress-section">
          <div className="progress-bar-container">
            <div
              className="progress-bar"
              style={{ width: `${progress * 100}%` }}
            />
          </div>
          <div className="progress-text">
            {jobStatus.message}
            <br />
            <small>
              {jobStatus.processed_count} / {jobStatus.total_count} questions
            </small>
          </div>
          <button className="cancel-btn" onClick={cancelJob}>
            Cancel
          </button>
        </div>
      ) : (
        <div className="action-buttons">
          <button
            className="action-btn evidence"
            onClick={() => startPipeline('evidence')}
            disabled={!selectedQuestions.length}
            title="Run evidence pipeline to build causal graphs"
          >
            📊 Run Evidence Pipeline
          </button>

          <button
            className="action-btn adaptive"
            onClick={() => startPipeline('adaptive_evidence')}
            disabled={!selectedQuestions.length}
            title="Run adaptive multi-agent evidence pipeline"
          >
            🔬 Run Adaptive Evidence
          </button>

          <button
            className="action-btn forecast"
            onClick={() => startPipeline('forecast')}
            disabled={!selectedQuestions.length}
            title="Run forecast on selected questions"
          >
            🎯 Run Forecast
          </button>

          <button
            className="action-btn clear"
            onClick={clearEvidence}
            disabled={!selectedQuestions.length}
            title="Clear evidence data for selected questions"
          >
            🗑️ Clear Evidence
          </button>
        </div>
      )}
    </div>
  )
}

export default PipelineControl
