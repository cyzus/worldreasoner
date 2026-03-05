import React, { useState, useEffect } from 'react';
import { fetchBenchmarkResults, fetchBenchmarkResult, fetchBenchmarkConditions } from '../api/graphApi';
import { JobSidebar, JobDetails } from './JobManager';
import { usePipelineJobs } from '../hooks/usePipelineJobs';
import './BenchmarkPage.css';

const BenchmarkPage = () => {
  // View toggle
  const [activeView, setActiveView] = useState('run'); // 'run' or 'results'

  // Conditions from API
  const [conditions, setConditions] = useState([]);
  const [selectedConditions, setSelectedConditions] = useState([]);
  const [loadingConditions, setLoadingConditions] = useState(false);

  // Benchmark config
  const [models, setModels] = useState(['gemini/gemini-2.5-flash']);
  const [newModel, setNewModel] = useState('');
  const [maxQuestions, setMaxQuestions] = useState(10);
  const [slot, setSlot] = useState('mid');
  const [source, setSource] = useState('all');
  const [domain, setDomain] = useState('all');
  const [resume, setResume] = useState(false);
  const [launching, setLaunching] = useState(false);

  // Job management via shared hook
  const {
    jobs,
    loadingJobs,
    loadJobs,
    selectedJobId,
    jobDetails,
    loadingDetails,
    selectJob
  } = usePipelineJobs('auto_benchmark');

  // Results view state
  const [benchmarkRuns, setBenchmarkRuns] = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [selectedRun, setSelectedRun] = useState(null);
  const [loadingRunDetail, setLoadingRunDetail] = useState(false);

  // Load conditions on mount
  useEffect(() => {
    loadConditions();
  }, []);

  // Load results when switching to results view
  useEffect(() => {
    if (activeView === 'results') {
      loadBenchmarkRuns();
    }
  }, [activeView]);

  const loadConditions = async () => {
    setLoadingConditions(true);
    try {
      const data = await fetchBenchmarkConditions();
      setConditions(data);
      // Select all by default
      setSelectedConditions(data.map(c => c.name));
    } catch (err) {
      console.error('Error loading conditions:', err);
    } finally {
      setLoadingConditions(false);
    }
  };

  const loadBenchmarkRuns = async () => {
    setLoadingRuns(true);
    try {
      const data = await fetchBenchmarkResults();
      setBenchmarkRuns(data);
    } catch (err) {
      console.error('Error loading benchmark runs:', err);
    } finally {
      setLoadingRuns(false);
    }
  };

  const handleRunClick = async (run) => {
    setLoadingRunDetail(true);
    try {
      const data = await fetchBenchmarkResult(run.run_id);
      setSelectedRun(data);
    } catch (err) {
      console.error('Error loading run details:', err);
    } finally {
      setLoadingRunDetail(false);
    }
  };

  const toggleCondition = (condName) => {
    setSelectedConditions(prev =>
      prev.includes(condName)
        ? prev.filter(c => c !== condName)
        : [...prev, condName]
    );
  };

  const addModel = () => {
    const trimmed = newModel.trim();
    if (trimmed && !models.includes(trimmed)) {
      setModels([...models, trimmed]);
      setNewModel('');
    }
  };

  const removeModel = (modelName) => {
    setModels(models.filter(m => m !== modelName));
  };

  const startBenchmark = async () => {
    if (selectedConditions.length === 0) {
      alert('Please select at least one condition');
      return;
    }
    if (models.length === 0) {
      alert('Please add at least one model');
      return;
    }

    setLaunching(true);
    try {
      const config = {
        conditions: selectedConditions,
        models,
        max_questions: maxQuestions,
        slot,
        resume,
      };
      if (source !== 'all') config.source = source;
      if (domain !== 'all') config.domain = domain;

      const response = await fetch('http://localhost:8018/api/pipelines/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pipeline_type: 'auto_benchmark',
          config
        })
      });

      const data = await response.json();
      await loadJobs();
      selectJob(data.job_id);
    } catch (err) {
      console.error('Error starting benchmark:', err);
      alert('Failed to start benchmark: ' + err.message);
    } finally {
      setLaunching(false);
    }
  };

  const formatDuration = (seconds) => {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    if (mins < 60) return `${mins}m ${secs}s`;
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    return `${hours}h ${remMins}m`;
  };

  return (
    <div className="benchmark-page page-container">
      <div className="benchmark-header page-header">
        <h2>Benchmark System</h2>
        <div className="header-actions">
          <button
            className={`view-btn ${activeView === 'run' ? 'active' : ''}`}
            onClick={() => setActiveView('run')}
          >
            Run Benchmark
          </button>
          <button
            className={`view-btn ${activeView === 'results' ? 'active' : ''}`}
            onClick={() => setActiveView('results')}
          >
            Results
          </button>
        </div>
      </div>

      {activeView === 'results' ? (
        <div className="benchmark-results-view">
          <div className="results-list-panel">
            <h3>Past Benchmark Runs</h3>
            {loadingRuns ? (
              <div className="loading">Loading runs...</div>
            ) : benchmarkRuns.length === 0 ? (
              <div className="no-data">No benchmark results found. Run a benchmark first.</div>
            ) : (
              <div className="runs-list">
                {benchmarkRuns.map(run => (
                  <div
                    key={run.run_id}
                    className={`run-item ${selectedRun?.auto_benchmark_info?.run_id === run.run_id ? 'active' : ''}`}
                    onClick={() => handleRunClick(run)}
                  >
                    <div className="run-item-header">
                      <span className="run-id">{run.run_id}</span>
                      <span className="run-duration">{formatDuration(run.duration_seconds)}</span>
                    </div>
                    <div className="run-item-meta">
                      <span>{run.question_count} questions</span>
                      <span>{run.conditions?.length || 0} conditions</span>
                      <span>{run.models?.length || 0} models</span>
                    </div>
                    <div className="run-item-time">
                      {run.timestamp ? new Date(run.timestamp).toLocaleString() : ''}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="results-detail-panel">
            {loadingRunDetail ? (
              <div className="loading">Loading benchmark details...</div>
            ) : !selectedRun ? (
              <div className="no-data">Select a benchmark run to view results</div>
            ) : (
              <div className="run-detail">
                {/* Summary Stats */}
                <div className="benchmark-summary-stats">
                  <div className="stat-card">
                    <div className="stat-label">Conditions</div>
                    <div className="stat-value">{selectedRun.configuration?.conditions?.length || 0}</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Models</div>
                    <div className="stat-value">{selectedRun.configuration?.models?.length || 0}</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Questions</div>
                    <div className="stat-value">{selectedRun.configuration?.question_count || 0}</div>
                  </div>
                  <div className="stat-card">
                    <div className="stat-label">Duration</div>
                    <div className="stat-value">{formatDuration(selectedRun.auto_benchmark_info?.duration_seconds)}</div>
                  </div>
                </div>

                {/* Leaderboard */}
                {selectedRun.comparative_summary?.leaderboard && (
                  <div className="leaderboard-section">
                    <h3>Leaderboard</h3>
                    <table className="data-table leaderboard-table">
                      <thead>
                        <tr>
                          <th>Rank</th>
                          <th>Condition</th>
                          <th>Model</th>
                          <th>Accuracy</th>
                          <th>Brier Score</th>
                          <th>Log Score</th>
                          <th>Questions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedRun.comparative_summary.leaderboard.map((entry, idx) => (
                          <tr key={`${entry.condition}-${entry.model}`} className={idx === 0 ? 'top-rank' : ''}>
                            <td className="rank-cell">#{idx + 1}</td>
                            <td>
                              <span className="condition-name">{entry.display_name}</span>
                            </td>
                            <td className="model-cell">{entry.model}</td>
                            <td className="metric-cell accuracy">
                              {(entry.accuracy * 100).toFixed(1)}%
                            </td>
                            <td className="metric-cell brier">
                              {entry.avg_brier_score?.toFixed(4) ?? 'N/A'}
                            </td>
                            <td className="metric-cell log-score">
                              {entry.avg_log_score?.toFixed(4) ?? 'N/A'}
                            </td>
                            <td className="metric-cell">
                              {entry.successful}/{entry.total_questions}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Per-condition breakdown */}
                {selectedRun.condition_results && (
                  <div className="condition-breakdown-section">
                    <h3>Per-Condition Breakdown</h3>
                    {Object.entries(selectedRun.condition_results).map(([condName, modelResults]) => (
                      <details key={condName} className="condition-detail">
                        <summary className="condition-summary">
                          <span className="condition-name">{condName}</span>
                          <span className="condition-models">{Object.keys(modelResults).length} model(s)</span>
                        </summary>
                        <div className="condition-content">
                          {Object.entries(modelResults).map(([modelName, result]) => (
                            <div key={modelName} className="model-result-card">
                              <div className="model-result-header">
                                <span className="model-name">{modelName}</span>
                                <span className="model-display-name">{result.display_name}</span>
                              </div>
                              <div className="model-result-stats">
                                <span>Accuracy: <strong>{(result.accuracy * 100).toFixed(1)}%</strong></span>
                                <span>Brier: <strong>{result.avg_brier_score?.toFixed(4) ?? 'N/A'}</strong></span>
                                <span>Log: <strong>{result.avg_log_score?.toFixed(4) ?? 'N/A'}</strong></span>
                                <span>Success: <strong>{result.successful}/{result.total_questions}</strong></span>
                                {result.failed > 0 && <span className="failed-count">Failed: {result.failed}</span>}
                              </div>
                            </div>
                          ))}
                        </div>
                      </details>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ) : (
        /* Run Benchmark View */
        <div className="page-content">
          <div className="page-sidebar">
            <div className="scroll-container">
              {/* Configuration Section */}
              <div className="benchmark-config-section">
                <h3>Benchmark Configuration</h3>

                {/* Conditions */}
                <div className="config-block">
                  <label className="config-block-label">Experiment Conditions</label>
                  {loadingConditions ? (
                    <div className="loading-small">Loading conditions...</div>
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

                {/* Models */}
                <div className="config-block">
                  <label className="config-block-label">Models</label>
                  <div className="models-list">
                    {models.map(model => (
                      <div key={model} className="model-tag">
                        <span>{model}</span>
                        <button onClick={() => removeModel(model)} className="remove-model-btn" title="Remove model">x</button>
                      </div>
                    ))}
                  </div>
                  <div className="add-model-row">
                    <input
                      type="text"
                      placeholder="e.g., gemini/gemini-2.5-pro"
                      value={newModel}
                      onChange={(e) => setNewModel(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && addModel()}
                    />
                    <button onClick={addModel} className="add-model-btn">Add</button>
                  </div>
                </div>

                {/* Other config */}
                <div className="config-grid">
                  <div className="config-item">
                    <label>Max Questions</label>
                    <input
                      type="number"
                      min="1"
                      max="1000"
                      value={maxQuestions}
                      onChange={(e) => setMaxQuestions(parseInt(e.target.value) || 1)}
                    />
                  </div>

                  <div className="config-item">
                    <label>Forecast Slot</label>
                    <select
                      value={slot}
                      onChange={(e) => setSlot(e.target.value)}
                    >
                      <option value="early">Early — 20% into window (harder)</option>
                      <option value="mid">Mid — 50% into window (default)</option>
                      <option value="late">Late — 80% into window (easier)</option>
                    </select>
                  </div>

                  <div className="config-item">
                    <label>Source</label>
                    <select value={source} onChange={(e) => setSource(e.target.value)}>
                      <option value="all">All Sources</option>
                      <option value="polymarket">Polymarket</option>
                      <option value="metaculus">Metaculus</option>
                      <option value="manual">Manual</option>
                    </select>
                  </div>

                  <div className="config-item">
                    <label>Domain</label>
                    <select value={domain} onChange={(e) => setDomain(e.target.value)}>
                      <option value="all">All Domains</option>
                      <option value="politics">Politics</option>
                      <option value="economics">Economics</option>
                      <option value="technology">Technology</option>
                      <option value="science">Science</option>
                      <option value="sports">Sports</option>
                      <option value="other">Other</option>
                    </select>
                  </div>
                </div>

                <div className="config-block">
                  <label className="resume-checkbox">
                    <input
                      type="checkbox"
                      checked={resume}
                      onChange={(e) => setResume(e.target.checked)}
                    />
                    Resume (skip already-completed triples)
                  </label>
                </div>

                <button
                  className="run-benchmark-btn"
                  onClick={startBenchmark}
                  disabled={launching || selectedConditions.length === 0 || models.length === 0}
                >
                  {launching ? 'Starting...' : `Start Benchmark (${selectedConditions.length} conditions x ${models.length} models)`}
                </button>
              </div>

              {/* Jobs Section */}
              <JobSidebar
                jobs={jobs}
                selectedJobId={selectedJobId}
                onJobClick={(job) => selectJob(job.job_id)}
                loading={loadingJobs}
                onRefresh={loadJobs}
                title="Recent Benchmark Jobs"
              />
            </div>
          </div>

          {/* Right Main Content - Job Details */}
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
                <div className="benchmark-placeholder">
                  <div className="placeholder-icon">&#x1F4CA;</div>
                  <h3>Auto-Benchmark System</h3>
                  <p>
                    Run ablation studies across 5 experimental conditions to evaluate
                    forecasting quality. Configure conditions, models, and questions in the sidebar,
                    then click "Start Benchmark" to begin.
                  </p>
                  <div className="placeholder-conditions">
                    {conditions.map(cond => (
                      <div key={cond.name} className="placeholder-condition-item">
                        <strong>{cond.display_name}</strong>: {cond.description}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default BenchmarkPage;
