import React, { useState, useEffect } from 'react';
import { fetchQuestions, fetchQuestionPriceHistory, fetchQuestionEvents } from '../api/graphApi';
import TimeSeriesChart from './TimeSeriesChart';
import ForecastGraph from './ForecastGraph';
import EvaluationDashboard from './EvaluationDashboard';
import { JobSidebar, JobDetails } from './JobManager';
import { usePipelineJobs } from '../hooks/usePipelineJobs';
import './ForecastPage.css';

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

  // Price history state
  const [priceHistoryData, setPriceHistoryData] = useState(null);
  const [loadingPriceHistory, setLoadingPriceHistory] = useState(false);
  const [priceHistoryInterval, setPriceHistoryInterval] = useState('max');
  const [questionRelatedEvents, setQuestionRelatedEvents] = useState([]);

  // Forecast configuration state (matches backend pipeline_runner.py parameters)
  const [forecastConfig, setForecastConfig] = useState({
    model: null,
    offset_days: 7,
    mode: 'container',
    enable_causal_tools: false,
    min_context_items: 3
  });

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

  useEffect(() => {
    loadQuestions();
  }, []);

  const loadQuestions = async () => {
    try {
      const data = await fetchQuestions();
      setQuestions(data);
    } catch (error) {
      console.error('Error fetching questions:', error);
    }
  };



  const handleQuestionClick = async (question) => {
    try {
      const questionId = question.id;
      setSelectedQuestion(question);

      if (question.source === 'polymarket') {
        await loadPriceHistory(questionId, priceHistoryInterval, questionId);
      }
    } catch (error) {
      console.error('Error handling question click:', error);
    }
  };

  const loadPriceHistory = async (questionId, interval = priceHistoryInterval, expectedQuestionId = null) => {
    setLoadingPriceHistory(true);
    try {
      const data = await fetchQuestionPriceHistory(questionId, interval);

      // Only update state if this is still the expected question
      // This prevents race conditions when clicking multiple questions quickly
      if (expectedQuestionId === null || expectedQuestionId === questionId) {
        setPriceHistoryData(data);
        // Note: fetchQuestionEvents returns metadata (event_ids, counts), not full event objects
        // For now, we'll pass an empty array to TimeSeriesChart
        // TODO: Fetch full event details if needed for visualization
        setQuestionRelatedEvents([]);
      }
    } catch (error) {
      console.error('Error fetching price history:', error);
      if (expectedQuestionId === null || expectedQuestionId === questionId) {
        setPriceHistoryData(null);
        setQuestionRelatedEvents([]);
      }
    } finally {
      setLoadingPriceHistory(false);
    }
  };

  const handleIntervalChange = async (interval) => {
    setPriceHistoryInterval(interval);
    if (selectedQuestion) {
      await loadPriceHistory(selectedQuestion.id, interval, selectedQuestion.id);
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
      const response = await fetch('http://localhost:8018/api/pipelines/jobs', {
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
      const response = await fetch(`http://localhost:8018/api/pipelines/jobs/${jobId}/results`);
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
      const response = await fetch(`http://localhost:8018/api/forecasts/${forecastId}/graph`);
      if (response.ok) {
        const data = await response.json();
        setForecastGraphData(data);
        setSelectedForecastId(forecastId);
      } else {
        console.log('No graph data for forecast:', forecastId);
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
                      Offset Days
                      <span style={{ fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px' }}>
                        - Days before question close date
                      </span>
                    </label>
                    <input
                      type="number"
                      min="0"
                      max="365"
                      value={forecastConfig.offset_days}
                      onChange={(e) => setForecastConfig({ ...forecastConfig, offset_days: parseInt(e.target.value) || 0 })}
                    />
                  </div>

                  <div className="config-item">
                    <label>
                      Min Context Items
                      <span style={{ fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px' }}>
                        - Minimum evidence items to use
                      </span>
                    </label>
                    <input
                      type="number"
                      min="1"
                      max="20"
                      value={forecastConfig.min_context_items}
                      onChange={(e) => setForecastConfig({ ...forecastConfig, min_context_items: parseInt(e.target.value) || 1 })}
                    />
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

                <button
                  className="run-forecast-btn"
                  onClick={startForecastPipeline}
                  disabled={selectedQuestions.length === 0}
                >
                  🎯 Run Forecast ({selectedQuestions.length} questions)
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
                <>
                  {/* Question Selection */}
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

                      <select
                        value={filterForecastStatus}
                        onChange={(e) => setFilterForecastStatus(e.target.value)}
                        className="filter-select"
                      >
                        <option value="all">All Forecast Status</option>
                        <option value="forecasted">Forecasted</option>
                        <option value="not_forecasted">Not Forecasted</option>
                      </select>

                      <select
                        value={filterForecastMode}
                        onChange={(e) => setFilterForecastMode(e.target.value)}
                        className="filter-select"
                      >
                        <option value="all">All Forecast Modes</option>
                        <option value="knowledge_only">Knowledge Only</option>
                        <option value="container">Container</option>
                        <option value="real_time">Real-Time</option>
                      </select>
                    </div>

                    <div className="questions-list">
                      {filteredQuestions.map(question => (
                        <div
                          key={question.id}
                          className={`question-item ${selectedQuestion?.id === question.id ? 'active' : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={selectedQuestions.includes(question.id)}
                            onChange={() => toggleQuestionSelection(question.id)}
                            onClick={(e) => e.stopPropagation()}
                          />
                          <div
                            className="question-content"
                            onClick={() => handleQuestionClick(question)}
                          >
                            <div className="question-text">{question.question_text}</div>
                            <div className="question-meta">
                              <span className="badge source">{question.source}</span>
                              {question.domain && <span className="badge domain">{question.domain}</span>}
                              {question.difficulty && (
                                <span className="badge difficulty">Diff: {question.difficulty}</span>
                              )}
                              {question.forecast_count > 0 && (
                                <span className="badge forecast-badge" title={`Forecasted ${question.forecast_count} times in modes: ${question.forecast_modes?.join(', ')}`}>
                                  🎯 {question.forecast_count}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Price History Visualization */}
                  {selectedQuestion && selectedQuestion.source === 'polymarket' && (
                    <div className="price-history-section">
                      <div className="price-history-header">
                        <h3>Price History - {selectedQuestion.question_text}</h3>
                        <div className="interval-selector">
                          {['1h', '6h', '1d', '1w', 'max'].map(interval => (
                            <button
                              key={interval}
                              className={`interval-btn ${priceHistoryInterval === interval ? 'active' : ''}`}
                              onClick={() => handleIntervalChange(interval)}
                            >
                              {interval}
                            </button>
                          ))}
                        </div>
                      </div>

                      {loadingPriceHistory ? (
                        <div className="loading">Loading price history...</div>
                      ) : priceHistoryData && priceHistoryData.price_history ? (
                        <TimeSeriesChart
                          priceHistory={priceHistoryData.price_history}
                          events={questionRelatedEvents}
                          targetEventId={selectedQuestion.target_event_id}
                          outcomes={priceHistoryData.outcomes || ['Yes', 'No']}
                        />
                      ) : (
                        <div className="no-data">No price history available</div>
                      )}
                    </div>
                  )}
                </>
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
