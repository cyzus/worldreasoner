import React, { useState, useEffect } from 'react'
import QuestionList from './QuestionList'
import PipelineControl from './PipelineControl'
import QuestionMonitor from './QuestionMonitor'
import { JobSidebar, JobDetails } from './JobManager'
import { usePipelineJobs } from '../hooks/usePipelineJobs'
import './PipelinePage.css'

const PipelinePage = ({ questions, onJobComplete }) => {
  const [selectedQuestions, setSelectedQuestions] = useState([])
  const [activeTab, setActiveTab] = useState('monitor') // 'monitor' | 'manual'

  // Use shared hook for job management
  const {
    jobs,
    loadingJobs,
    loadJobs,
    selectedJobId,
    jobDetails,
    loadingDetails,
    selectJob
  } = usePipelineJobs(null) // Show all jobs for now (or specific types if needed)

  // Handle job completion from control panel
  const handleJobComplete = (results) => {
    onJobComplete?.(results)
    loadJobs() // Refresh list immediately
  }

  return (
    <div className="pipeline-page page-container">
      <div className="pipeline-page-header page-header">
        <h2>Evidence Automation</h2>
        <div style={{ display: 'flex', gap: '1rem', marginLeft: '2rem' }}>
          <button
            onClick={() => setActiveTab('monitor')}
            style={{
              fontWeight: activeTab === 'monitor' ? 'bold' : 'normal',
              color: activeTab === 'monitor' ? '#2563eb' : '#6b7280',
              border: activeTab === 'monitor' ? '1px solid #2563eb' : '1px solid transparent',
              background: activeTab === 'monitor' ? '#eff6ff' : 'transparent',
              padding: '0.25rem 0.75rem',
              borderRadius: '0.25rem',
              cursor: 'pointer'
            }}
          >
            Monitor & Auto-Collect
          </button>
          <button
            onClick={() => setActiveTab('manual')}
            style={{
              fontWeight: activeTab === 'manual' ? 'bold' : 'normal',
              color: activeTab === 'manual' ? '#2563eb' : '#6b7280',
              border: activeTab === 'manual' ? '1px solid #2563eb' : '1px solid transparent',
              background: activeTab === 'manual' ? '#eff6ff' : 'transparent',
              padding: '0.25rem 0.75rem',
              borderRadius: '0.25rem',
              cursor: 'pointer'
            }}
          >
            Manual Control & History
          </button>
        </div>
      </div>

      <div className="page-content" style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, overflow: 'hidden', display: activeTab === 'monitor' ? 'block' : 'none' }}>
          <QuestionMonitor activeJobs={jobs} />
        </div>

        <div style={{ display: activeTab === 'manual' ? 'flex' : 'none', flex: 1, overflow: 'hidden' }}>
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

              {/* Job History - Replaced with shared component */}
              <JobSidebar
                jobs={jobs}
                selectedJobId={selectedJobId}
                onJobClick={(job) => selectJob(job.job_id)}
                loading={loadingJobs}
                onRefresh={loadJobs}
                title="Recent Jobs"
              />
            </div>
          </div>

          {/* Right Main Content: Question Selection or Job Details */}
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
                /* If no job selected, show questions list for selection */
                <div className="pipeline-questions-section">
                  <div className="section-header">
                    <h3>Select Questions</h3>
                    <span className="selected-badge">
                      {selectedQuestions.length} selected
                    </span>
                  </div>
                  <QuestionList
                    questions={questions}
                    activeJobs={jobs}
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
    </div>
  )
}

export default PipelinePage
