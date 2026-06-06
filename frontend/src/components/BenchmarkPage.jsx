import React, { useState, useEffect } from 'react'
import { fetchBenchmarkConditions } from '../api/graphApi'
import { JobSidebar, JobDetails } from './JobManager'
import { usePipelineJobs } from '../hooks/usePipelineJobs'
import BenchmarkMatrix from './benchmark/BenchmarkMatrix'
import './BenchmarkPage.css'

const BenchmarkPage = () => {

  // Conditions
  const [conditions, setConditions]           = useState([])
  const [selectedConditions, setSelectedConditions] = useState([])
  const [loadingConditions, setLoadingConditions] = useState(false)

  // Run config
  const [models, setModels]         = useState(['gemini/gemini-2.5-flash'])
  const [newModel, setNewModel]     = useState('')
  const [maxQuestions, setMaxQuestions] = useState(10)
  const [slot, setSlot]             = useState('mid')
  const [source, setSource]         = useState('all')
  const [domain, setDomain]         = useState('all')
  const [resume, setResume]         = useState(false)
  const [launching, setLaunching]   = useState(false)

  const { jobs, loadingJobs, loadJobs, selectedJobId, jobDetails, loadingDetails, selectJob } =
    usePipelineJobs('auto_benchmark')

  useEffect(() => {
    setLoadingConditions(true)
    fetchBenchmarkConditions()
      .then(data => {
        setConditions(data)
        setSelectedConditions(data.map(c => c.name))
      })
      .catch(err => console.error('Error loading conditions:', err))
      .finally(() => setLoadingConditions(false))
  }, [])

  const toggleCondition = (name) =>
    setSelectedConditions(prev =>
      prev.includes(name) ? prev.filter(c => c !== name) : [...prev, name]
    )

  const addModel = () => {
    const t = newModel.trim()
    if (t && !models.includes(t)) { setModels([...models, t]); setNewModel('') }
  }

  const startBenchmark = async () => {
    if (!selectedConditions.length) { alert('Select at least one condition'); return }
    if (!models.length) { alert('Add at least one model'); return }
    setLaunching(true)
    try {
      const config = { conditions: selectedConditions, models, max_questions: maxQuestions, slot, resume }
      if (source !== 'all') config.source = source
      if (domain !== 'all') config.domain = domain
      const res = await fetch('/api/pipelines/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pipeline_type: 'auto_benchmark', config }),
      })
      const data = await res.json()
      await loadJobs()
      selectJob(data.job_id)
    } catch (err) {
      console.error('Error starting benchmark:', err)
      alert('Failed to start benchmark: ' + err.message)
    } finally {
      setLaunching(false)
    }
  }

  return (
    <div className="benchmark-page page-container">
      <div className="benchmark-header page-header">
        <h2>Benchmark</h2>
      </div>

      <div className="page-content">
        {/* ── Left sidebar: config + jobs ── */}
        <div className="page-sidebar">
          <div className="scroll-container">
            <div className="benchmark-config-section">
              <h3>Configuration</h3>

              <div className="config-block">
                <label className="config-block-label">Conditions</label>
                {loadingConditions ? (
                  <div className="loading-small">Loading…</div>
                ) : (
                  <div className="conditions-grid">
                    {conditions.map(cond => (
                      <label key={cond.name} className="condition-checkbox" title={cond.description}>
                        <input
                          type="checkbox"
                          checked={selectedConditions.includes(cond.name)}
                          onChange={() => toggleCondition(cond.name)}
                        />
                        <div className="condition-info">
                          <span className="condition-display-name">{cond.display_name}</span>
                          <span className="condition-desc">{cond.description}</span>
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              <div className="config-block">
                <label className="config-block-label">Models</label>
                <div className="models-list">
                  {models.map(m => (
                    <div key={m} className="model-tag">
                      <span>{m}</span>
                      <button onClick={() => setModels(models.filter(x => x !== m))} className="remove-model-btn">×</button>
                    </div>
                  ))}
                </div>
                <div className="add-model-row">
                  <input
                    placeholder="e.g., openai/gpt-4o"
                    value={newModel}
                    onChange={e => setNewModel(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && addModel()}
                  />
                  <button onClick={addModel} className="add-model-btn">Add</button>
                </div>
              </div>

              <div className="config-grid">
                <div className="config-item">
                  <label>Max Questions</label>
                  <input type="number" min="1" max="1000" value={maxQuestions}
                    onChange={e => setMaxQuestions(parseInt(e.target.value) || 1)} />
                </div>
                <div className="config-item">
                  <label>Slot</label>
                  <select value={slot} onChange={e => setSlot(e.target.value)}>
                    <option value="early">Early (harder)</option>
                    <option value="mid">Mid (default)</option>
                    <option value="late">Late (easier)</option>
                  </select>
                </div>
                <div className="config-item">
                  <label>Source</label>
                  <select value={source} onChange={e => setSource(e.target.value)}>
                    <option value="all">All</option>
                    <option value="polymarket">Polymarket</option>
                    <option value="manual">Manual</option>
                  </select>
                </div>
                <div className="config-item">
                  <label>Domain</label>
                  <select value={domain} onChange={e => setDomain(e.target.value)}>
                    <option value="all">All</option>
                    <option value="politics">Politics</option>
                    <option value="economics">Economics</option>
                    <option value="technology">Technology</option>
                    <option value="science">Science</option>
                    <option value="sports">Sports</option>
                  </select>
                </div>
              </div>

              <div className="config-block">
                <label className="resume-checkbox">
                  <input type="checkbox" checked={resume} onChange={e => setResume(e.target.checked)} />
                  Resume (skip completed triples)
                </label>
              </div>

              <button
                className="run-benchmark-btn"
                onClick={startBenchmark}
                disabled={launching || !selectedConditions.length || !models.length}
              >
                {launching
                  ? 'Starting…'
                  : `Start (${selectedConditions.length} × ${models.length})`}
              </button>
            </div>

            <JobSidebar
              jobs={jobs}
              selectedJobId={selectedJobId}
              onJobClick={job => selectJob(job.job_id)}
              loading={loadingJobs}
              onRefresh={loadJobs}
              title="Recent Jobs"
            />
          </div>
        </div>

        {/* ── Right panel: matrix always visible; job details overlay when selected ── */}
        <div className="page-main" style={{ position: 'relative' }}>
          {selectedJobId && jobDetails ? (
            <div className="scroll-container">
              <JobDetails job={jobDetails} onClose={() => selectJob(null)} />
            </div>
          ) : loadingDetails ? (
            <div className="loading-details">
              <div className="loading-spinner" />
              <div>Loading job details…</div>
            </div>
          ) : (
            <BenchmarkMatrix />
          )}
        </div>
      </div>
    </div>
  )
}

export default BenchmarkPage
