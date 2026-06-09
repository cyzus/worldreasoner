import React, { useEffect, useMemo, useRef, useState } from 'react';
import { fetchQuestions, fetchQuestionSlotPreview } from '../api/graphApi';
import ForecastGraph from './ForecastGraph';
import EvaluationDashboard from './EvaluationDashboard';
import QuestionCard from './QuestionCard';
import { JobSidebar, JobDetails } from './JobManager';
import { usePipelineJobs } from '../hooks/usePipelineJobs';
import { ForecastTab } from './CaseStudyView/ForecastTab';
import './ForecastPage.css';

const formatDate = (value) => {
  if (!value) return 'N/A';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleDateString();
};

const formatValue = (value) => {
  if (value === null || value === undefined || value === '') return 'N/A';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  return String(value);
};

/** Visual timeline bar showing where the simulated date falls in the forecast window. */
const SlotPreviewBar = ({ preview }) => {
  const start = new Date(preview.window_start);
  const end = new Date(preview.window_end);
  const sim = new Date(preview.simulated_date);
  const pct = Math.round(((sim - start) / (end - start)) * 100);
  const fmt = (d) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <div className="slot-preview-bar-wrap">
      <div className="slot-preview-bar">
        <div className="slot-preview-fill" style={{ width: `${pct}%` }} />
        <div className="slot-preview-marker" style={{ left: `${pct}%` }} title={`Simulated: ${fmt(sim)}`} />
      </div>
      <div className="slot-preview-labels">
        <span>{fmt(start)}</span>
        <span className="slot-preview-sim-date">{fmt(sim)}</span>
        <span>{fmt(end)}</span>
      </div>
    </div>
  );
};

const ForecastPage = ({
  onQuestionSelect
}) => {
  const [questions, setQuestions] = useState([]);
  const [selectedQuestion, setSelectedQuestion] = useState(null);
  const [selectedQuestions, setSelectedQuestions] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterDomain, setFilterDomain] = useState('all');
  const [filterSource, setFilterSource] = useState('all');
  const [filterForecastStatus, setFilterForecastStatus] = useState('all');
  const [filterForecastMode, setFilterForecastMode] = useState('all');

  // Forecast configuration state (matches backend pipeline_runner.py parameters)
  const [forecastConfig, setForecastConfig] = useState({
    model: null,
    slot: 'mid',
    mode: 'container',
    enable_causal_tools: false,
  });

  // Slot preview for the highlighted question
  const [slotPreview, setSlotPreview] = useState(null);
  const [slotPreviewError, setSlotPreviewError] = useState(null);
  const [loadingSlotPreview, setLoadingSlotPreview] = useState(false);

  // Job management via shared hook
  const {
    jobs,
    loadingJobs,
    loadJobs,
    selectedJobId,
    jobDetails,
    loadingDetails,
    selectJob
  } = usePipelineJobs('forecast');

  // Results state
  const [forecastResults, setForecastResults] = useState(null);
  const [loadingResults, setLoadingResults] = useState(false);
  const [forecastGraphData, setForecastGraphData] = useState(null);
  const [selectedForecastId, setSelectedForecastId] = useState(null);

  // View state
  const [activeView, setActiveView] = useState('management'); // 'management' or 'evaluation'
  const listPaneRef = useRef(null);
  const detailPaneRef = useRef(null);

  useEffect(() => {
    loadQuestions();
  }, []);

  useEffect(() => {
    if (selectedQuestion) {
      if (detailPaneRef.current) {
        detailPaneRef.current.scrollTop = 0;
      }
      return;
    }

    if (listPaneRef.current) {
      listPaneRef.current.scrollTop = 0;
    }
  }, [selectedQuestion?.id]);

  useEffect(() => {
    if (!selectedQuestion) {
      setSlotPreview(null);
      setSlotPreviewError(null);
      return;
    }
    let cancelled = false;
    setLoadingSlotPreview(true);
    setSlotPreviewError(null);
    fetchQuestionSlotPreview(selectedQuestion.id, forecastConfig.slot)
      .then(data => { if (!cancelled) { setSlotPreview(data); setSlotPreviewError(null); } })
      .catch(err => {
        if (!cancelled) {
          setSlotPreview(null);
          const msg = err?.response?.data?.detail || err?.message || 'Unknown error';
          setSlotPreviewError(msg);
        }
      })
      .finally(() => { if (!cancelled) setLoadingSlotPreview(false); });
    return () => { cancelled = true; };
  }, [selectedQuestion?.id, forecastConfig.slot]);

  const loadQuestions = async () => {
    try {
      const data = await fetchQuestions();
      setQuestions(data);
    } catch (error) {
      console.error('Error fetching questions:', error);
    }
  };



  const handleQuestionClick = (question) => {
    setSelectedQuestion(question);
    if (onQuestionSelect) {
      onQuestionSelect(question.id);
    }
  };

  const toggleQuestionSelection = (questionId) => {
    setSelectedQuestions(prev =>
      prev.includes(questionId)
        ? prev.filter(id => id !== questionId)
        : [...prev, questionId]
    );
  };

  const startForecastPipeline = async () => {
    if (selectedQuestions.length === 0) {
      alert('Please select at least one question');
      return;
    }

    try {
      const response = await fetch('/api/pipelines/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question_ids: selectedQuestions,
          pipeline_type: 'forecast',
          config: forecastConfig
        })
      });

      const data = await response.json();
      // Refresh jobs and select the new one
      await loadJobs();
      selectJob(data.job_id);
    } catch (error) {
      console.error('Error starting forecast:', error);
    }
  };

  const fetchForecastResults = async (jobId) => {
    setLoadingResults(true);
    try {
      const response = await fetch(`/api/pipelines/jobs/${jobId}/results`);
      const data = await response.json();
      setForecastResults(data);
    } catch (error) {
      console.error('Error fetching results:', error);
    } finally {
      setLoadingResults(false);
    }
  };

  const fetchForecastGraph = async (forecastId) => {
    try {
      const response = await fetch(`/api/forecasts/${forecastId}/graph`);
      if (response.ok) {
        const data = await response.json();
        setForecastGraphData(data);
        setSelectedForecastId(forecastId);
      } else {
        setForecastGraphData(null);
      }
    } catch (error) {
      console.error('Error fetching forecast graph:', error);
      setForecastGraphData(null);
    }
  };

  const filteredQuestions = questions.filter(q => {
    const matchesSearch = q.question_text.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesDomain = filterDomain === 'all' || q.domain === filterDomain;
    const matchesSource = filterSource === 'all' || q.source === filterSource;

    // Integrated Forecast Filter Logic
    const hasForecasts = q.forecast_count > 0;
    let matchesForecast = true;

    if (filterForecastStatus === 'not_forecasted') {
      if (filterForecastMode !== 'all') {
        // INTERPRETATION: "Not Forecasted" + "Mode X" => "Missing Mode X"
        // Show questions that do NOT have a forecast in this mode
        // (Includes questions with 0 forecasts, and questions with other modes but not this one)
        matchesForecast = !hasForecasts || !q.forecast_modes || !q.forecast_modes.includes(filterForecastMode);
      } else {
        // Strict "Not Forecasted" => Count is 0
        matchesForecast = !hasForecasts;
      }
    } else {
      // Logic for 'all' or 'forecasted' status

      // 1. Check Status constraint
      if (filterForecastStatus === 'forecasted' && !hasForecasts) {
        matchesForecast = false;
      }

      // 2. Check Mode constraint (Positive)
      if (matchesForecast && filterForecastMode !== 'all') {
        matchesForecast = hasForecasts && q.forecast_modes && q.forecast_modes.includes(filterForecastMode);
      }
    }

    return matchesSearch && matchesDomain && matchesSource && matchesForecast;
  });

  const domains = [...new Set(questions.map(q => q.domain))].filter(Boolean);
  const sources = [...new Set(questions.map(q => q.source))].filter(Boolean);

  const forecastStatusCounts = useMemo(() => {
    const counts = {
      all: questions.length,
      forecasted: 0,
      not_forecasted: 0,
    };
    questions.forEach((q) => {
      if ((q.forecast_count || 0) > 0) counts.forecasted += 1;
      else counts.not_forecasted += 1;
    });
    return counts;
  }, [questions]);

  const hasFilterOverrides =
    searchTerm ||
    filterDomain !== 'all' ||
    filterSource !== 'all' ||
    filterForecastStatus !== 'all' ||
    filterForecastMode !== 'all';

  const clearFilters = () => {
    setSearchTerm('');
    setFilterDomain('all');
    setFilterSource('all');
    setFilterForecastStatus('all');
    setFilterForecastMode('all');
  };

  const allFilteredSelected = filteredQuestions.length > 0 && filteredQuestions.every(q => selectedQuestions.includes(q.id));

  const handleSelectAll = () => {
    if (allFilteredSelected) {
      // Deselect filtered
      const filteredIds = new Set(filteredQuestions.map(q => q.id));
      setSelectedQuestions(prev => prev.filter(id => !filteredIds.has(id)));
    } else {
      // Select all filtered
      const filteredIds = filteredQuestions.map(q => q.id);
      setSelectedQuestions(prev => {
        const newSet = new Set([...prev, ...filteredIds]);
        return Array.from(newSet);
      });
    }
  };

  return (
    <div className="forecast-page page-container">
      <div className="forecast-header page-header">
        <h2>🎯 Forecast System</h2>
        <div className="header-actions">
          <button
            className={`view-btn ${activeView === 'management' ? 'active' : ''}`}
            onClick={() => setActiveView('management')}
          >
            Manage & Run
          </button>
          <button
            className={`view-btn ${activeView === 'evaluation' ? 'active' : ''}`}
            onClick={() => setActiveView('evaluation')}
          >
            Evaluation & Metrics
          </button>
        </div>
      </div>

      {activeView === 'evaluation' ? (
        <EvaluationDashboard />
      ) : (
        <div className="page-content">
          {/* Left Sidebar - Configuration, Jobs & Results */}
          <div className="page-sidebar">
            <div className="scroll-container">
              {/* Configuration Section */}
              <div className="forecast-config-section">
                <h3>Forecast Configuration</h3>

                <div className="config-grid">
                  <div className="config-item">
                    <label>
                      Model (optional)
                      <span style={{ fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px' }}>
                        - LiteLLM identifier
                      </span>
                    </label>
                    <input
                      type="text"
                      placeholder="e.g., gemini/gemini-2.5-flash (leave empty for default)"
                      value={forecastConfig.model || ''}
                      onChange={(e) => setForecastConfig({ ...forecastConfig, model: e.target.value || null })}
                    />
                  </div>

                  <div className="config-item">
                    <label>
                      Forecast Slot
                      <span style={{ fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px' }}>
                        - Position within forecast window
                      </span>
                    </label>
                    <select
                      value={forecastConfig.slot}
                      onChange={(e) => setForecastConfig({ ...forecastConfig, slot: e.target.value })}
                      style={{
                        width: '100%',
                        padding: '8px',
                        borderRadius: '4px',
                        border: '1px solid #ddd',
                        fontSize: '14px'
                      }}
                    >
                      <option value="early">Early — 20% into window (harder)</option>
                      <option value="mid">Mid — 50% into window (default)</option>
                      <option value="late">Late — 80% into window (easier)</option>
                    </select>
                  </div>

                  <div className="config-item">
                    <label>
                      Forecast Mode
                      <span style={{ fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px' }}>
                        - What information can the agent access?
                      </span>
                    </label>
                    <select
                      value={forecastConfig.mode}
                      onChange={(e) => setForecastConfig({ ...forecastConfig, mode: e.target.value })}
                      style={{
                        width: '100%',
                        padding: '8px',
                        borderRadius: '4px',
                        border: '1px solid #ddd',
                        fontSize: '14px'
                      }}
                    >
                      <option value="knowledge_only">Knowledge Only - LLM inherent knowledge</option>
                      <option value="container">Container - Temporal research (default)</option>
                      <option value="real_time">Real-Time - Live web search</option>
                    </select>
                  </div>

                  <div className="config-item">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <input
                        type="checkbox"
                        checked={forecastConfig.enable_causal_tools}
                        onChange={(e) => setForecastConfig({ ...forecastConfig, enable_causal_tools: e.target.checked })}
                        style={{ width: '18px', height: '18px', margin: 0, accentColor: '#4CAF50' }}
                      />
                      Enable Causal Reasoning Tools
                      <span style={{ fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px' }}>
                        - Build causal graphs during forecasting
                      </span>
                    </label>
                  </div>
                </div>

                {/* Slot preview for the currently highlighted question */}
                {selectedQuestion && (
                  <div className="slot-preview">
                    <div className="slot-preview-title">
                      Simulated date preview
                      <span className="slot-preview-question">{selectedQuestion.question_text.slice(0, 60)}{selectedQuestion.question_text.length > 60 ? '…' : ''}</span>
                    </div>
                    {loadingSlotPreview ? (
                      <div className="slot-preview-loading">Calculating…</div>
                    ) : slotPreview ? (
                      <>
                        <SlotPreviewBar preview={slotPreview} />
                        <div className="slot-preview-meta">
                          <span>{slotPreview.horizon_days}d window</span>
                          <span>{slotPreview.evidence_count_at_date} / {slotPreview.total_evidence} articles available</span>
                        </div>
                      </>
                    ) : slotPreviewError ? (
                      <div className="slot-preview-error">{slotPreviewError}</div>
                    ) : (
                      <div className="slot-preview-loading">No window data</div>
                    )}
                  </div>
                )}

                <button
                  className="run-forecast-btn"
                  onClick={startForecastPipeline}
                  disabled={selectedQuestions.length === 0}
                >
                  Run Forecast ({selectedQuestions.length} questions)
                </button>
              </div>

              {/* Jobs Section */}
              <JobSidebar
                jobs={jobs}
                selectedJobId={selectedJobId}
                onJobClick={(job) => selectJob(job.job_id)}
                loading={loadingJobs}
                onRefresh={loadJobs}
                title="Recent Forecast Jobs"
              />

              {/* Forecast Results Display */}
              {forecastResults && (
                <div className="forecast-results-section">
                  <h3>Forecast Results</h3>
                  {loadingResults ? (
                    <div className="loading">Loading results...</div>
                  ) : (
                    <div className="results-content">
                      {/* Show forecast IDs from processed results */}
                      {forecastResults.processed_details && forecastResults.processed_details.length > 0 && (
                        <div className="forecast-list">
                          <h4>Forecasts Generated:</h4>
                          {forecastResults.processed_details.map((item, idx) => (
                            <div key={idx} className="forecast-item">
                              <button
                                onClick={() => item.forecast_id && fetchForecastGraph(item.forecast_id)}
                                className="view-graph-btn"
                              >
                                View Graph for {item.id}
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                      <details>
                        <summary>Full Results JSON</summary>
                        <pre>{JSON.stringify(forecastResults, null, 2)}</pre>
                      </details>
                    </div>
                  )}
                </div>
              )}

              {/* Forecast Graph Display */}
              {forecastGraphData && (
                <div className="forecast-graph-section">
                  <div className="graph-header">
                    <h3>Causal Reasoning Graph</h3>
                    {selectedForecastId && (
                      <span className="forecast-id">Forecast: {selectedForecastId}</span>
                    )}
                  </div>
                  <ForecastGraph graphData={forecastGraphData} />
                </div>
              )}
            </div>
          </div>

          {/* Right Main Content - Job Details or Questions & Price History */}
          <div className="page-main">
            <div className="scroll-container forecast-main-scroll">
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
                <div className={`forecast-slide-shell ${selectedQuestion ? 'show-detail' : ''}`}>
                  <div className="forecast-slide-track">
                    <section ref={listPaneRef} className="forecast-pane forecast-pane-list">
                      <div className="forecast-questions-panel">
                        <div className="questions-header">
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <input
                              type="checkbox"
                              checked={allFilteredSelected}
                              onChange={handleSelectAll}
                              title="Select all filtered questions"
                              style={{ width: '18px', height: '18px', cursor: 'pointer', accentColor: '#4CAF50' }}
                            />
                            <h3>Questions</h3>
                          </div>
                          <div className="selection-info">
                            {selectedQuestions.length} selected
                          </div>
                        </div>

                        <div className="questions-filters">
                          <input
                            type="text"
                            placeholder="Search questions..."
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                            className="search-input"
                          />

                          <div className="forecast-filter-row">
                            <select
                              value={filterDomain}
                              onChange={(e) => setFilterDomain(e.target.value)}
                              className="filter-select"
                            >
                              <option value="all">All Domains</option>
                              {domains.map(domain => (
                                <option key={domain} value={domain}>{domain}</option>
                              ))}
                            </select>

                            <select
                              value={filterSource}
                              onChange={(e) => setFilterSource(e.target.value)}
                              className="filter-select"
                            >
                              <option value="all">All Sources</option>
                              {sources.map(source => (
                                <option key={source} value={source}>{source}</option>
                              ))}
                            </select>
                          </div>

                          <div className="forecast-chip-group" aria-label="Forecast status filter">
                            <button
                              type="button"
                              className={`forecast-chip ${filterForecastStatus === 'all' ? 'active' : ''}`}
                              onClick={() => setFilterForecastStatus('all')}
                            >
                              All ({forecastStatusCounts.all})
                            </button>
                            <button
                              type="button"
                              className={`forecast-chip status-forecasted ${filterForecastStatus === 'forecasted' ? 'active' : ''}`}
                              onClick={() => setFilterForecastStatus('forecasted')}
                            >
                              Forecasted ({forecastStatusCounts.forecasted})
                            </button>
                            <button
                              type="button"
                              className={`forecast-chip status-missing ${filterForecastStatus === 'not_forecasted' ? 'active' : ''}`}
                              onClick={() => setFilterForecastStatus('not_forecasted')}
                            >
                              Missing Forecast ({forecastStatusCounts.not_forecasted})
                            </button>
                          </div>

                          <div className="forecast-chip-group" aria-label="Forecast mode filter">
                            <button
                              type="button"
                              className={`forecast-chip ${filterForecastMode === 'all' ? 'active' : ''}`}
                              onClick={() => setFilterForecastMode('all')}
                            >
                              All Modes
                            </button>
                            <button
                              type="button"
                              className={`forecast-chip mode-knowledge ${filterForecastMode === 'knowledge_only' ? 'active' : ''}`}
                              onClick={() => setFilterForecastMode('knowledge_only')}
                            >
                              Knowledge Only
                            </button>
                            <button
                              type="button"
                              className={`forecast-chip mode-container ${filterForecastMode === 'container' ? 'active' : ''}`}
                              onClick={() => setFilterForecastMode('container')}
                            >
                              Container
                            </button>
                            <button
                              type="button"
                              className={`forecast-chip mode-realtime ${filterForecastMode === 'real_time' ? 'active' : ''}`}
                              onClick={() => setFilterForecastMode('real_time')}
                            >
                              Real-Time
                            </button>
                          </div>

                          <div className="forecast-filter-meta">
                            <span>{filteredQuestions.length} questions shown</span>
                            {hasFilterOverrides && (
                              <button type="button" className="forecast-clear-btn" onClick={clearFilters}>
                                Clear filters
                              </button>
                            )}
                          </div>
                        </div>

                        <div className="questions-list">
                          {filteredQuestions.map(question => (
                            <QuestionCard
                              key={question.id}
                              question={question}
                              isSelected={selectedQuestion?.id === question.id}
                              isMultiSelected={selectedQuestions.includes(question.id)}
                              onToggleSelect={() => toggleQuestionSelection(question.id)}
                              onClick={() => handleQuestionClick(question)}
                              showCheckbox={true}
                              showSelectionStyle={true}
                            />
                          ))}
                        </div>
                      </div>
                    </section>

                    <section ref={detailPaneRef} className="forecast-pane forecast-pane-detail">
                      <div className="forecast-history-panel">
                        <div className="forecast-history-header">
                          <button
                            className="forecast-back-btn"
                            onClick={() => setSelectedQuestion(null)}
                            type="button"
                          >
                            Back to questions
                          </button>
                          <h3>Forecast History</h3>
                          <span className="forecast-history-question">
                            {selectedQuestion?.question_text || 'Select a question to view forecast history.'}
                          </span>
                        </div>
                        {selectedQuestion && (
                          <div className="forecast-question-brief">
                            <div className="forecast-question-meta-grid">
                              <span className="forecast-question-chip"><strong>Source:</strong> {formatValue(selectedQuestion.source)}</span>
                              <span className="forecast-question-chip"><strong>Domain:</strong> {formatValue(selectedQuestion.domain)}</span>
                              <span className="forecast-question-chip"><strong>Type:</strong> {formatValue(selectedQuestion.question_type)}</span>
                              <span className="forecast-question-chip"><strong>Difficulty:</strong> {formatValue(selectedQuestion.difficulty)}</span>
                              <span className="forecast-question-chip"><strong>Ground Truth:</strong> {formatValue(selectedQuestion.ground_truth)}</span>
                              <span className="forecast-question-chip"><strong>Resolution:</strong> {formatDate(selectedQuestion.resolution_date)}</span>
                              <span className="forecast-question-chip"><strong>Quality:</strong> {formatValue(selectedQuestion.quality_score)}</span>
                              <span className="forecast-question-chip"><strong>Forecasts:</strong> {formatValue(selectedQuestion.forecast_count)}</span>
                            </div>

                            {(selectedQuestion.context || selectedQuestion.resolution_criteria) && (
                              <div className="forecast-question-extra">
                                {selectedQuestion.context && (
                                  <p>
                                    <strong>Context:</strong> {selectedQuestion.context}
                                  </p>
                                )}
                                {selectedQuestion.resolution_criteria && (
                                  <p>
                                    <strong>Resolution Criteria:</strong> {selectedQuestion.resolution_criteria}
                                  </p>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                        {selectedQuestion ? (
                          <ForecastTab selectedQuestion={selectedQuestion} />
                        ) : (
                          <div className="cs-empty">Select a question from the list to view its forecasts.</div>
                        )}
                      </div>
                    </section>
                  </div>
                </div>
              )
              }
            </div >
          </div >
        </div>
      )}
    </div >
  );
};

export default ForecastPage;
