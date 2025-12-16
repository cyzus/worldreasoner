import React, { useState, useEffect } from 'react';
import { fetchQuestions, fetchQuestionPriceHistory, fetchQuestionEvents } from '../api/graphApi';
import TimeSeriesChart from './TimeSeriesChart';
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

  // Job management state
  const [jobs, setJobs] = useState([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [activeJobId, setActiveJobId] = useState(null);

  // Results state
  const [forecastResults, setForecastResults] = useState(null);
  const [loadingResults, setLoadingResults] = useState(false);

  useEffect(() => {
    loadQuestions();
    fetchRecentJobs();

    // Refresh jobs every 5 seconds
    const interval = setInterval(fetchRecentJobs, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadQuestions = async () => {
    try {
      const data = await fetchQuestions();
      setQuestions(data);
    } catch (error) {
      console.error('Error fetching questions:', error);
    }
  };

  const fetchRecentJobs = async () => {
    setLoadingJobs(true);
    try {
      const response = await fetch('http://localhost:8018/api/pipelines/jobs?limit=20');
      const data = await response.json();
      const forecastJobs = data.filter(job => job.pipeline_type === 'forecast');
      setJobs(forecastJobs);
    } catch (error) {
      console.error('Error fetching jobs:', error);
    } finally {
      setLoadingJobs(false);
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
      setActiveJobId(data.job_id);
      await fetchRecentJobs();
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

  const filteredQuestions = questions.filter(q => {
    const matchesSearch = q.question_text.toLowerCase().includes(searchTerm.toLowerCase());
    const matchesDomain = filterDomain === 'all' || q.domain === filterDomain;
    const matchesSource = filterSource === 'all' || q.source === filterSource;
    return matchesSearch && matchesDomain && matchesSource;
  });

  const domains = [...new Set(questions.map(q => q.domain))].filter(Boolean);
  const sources = [...new Set(questions.map(q => q.source))].filter(Boolean);

  return (
    <div className="forecast-page">
      <div className="forecast-header">
        <h2>🎯 Forecast Management</h2>
      </div>

      <div className="forecast-content">
        {/* Left Sidebar - Configuration, Jobs & Results */}
        <div className="forecast-sidebar">
          {/* Configuration Section */}
          <div className="forecast-config-section">
            <h3>Forecast Configuration</h3>

            <div className="config-grid">
              <div className="config-item">
                <label>
                  Model (optional)
                  <span style={{fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px'}}>
                    - LiteLLM identifier
                  </span>
                </label>
                <input
                  type="text"
                  placeholder="e.g., gemini/gemini-2.5-flash (leave empty for default)"
                  value={forecastConfig.model || ''}
                  onChange={(e) => setForecastConfig({...forecastConfig, model: e.target.value || null})}
                />
              </div>

              <div className="config-item">
                <label>
                  Offset Days
                  <span style={{fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px'}}>
                    - Days before question close date
                  </span>
                </label>
                <input
                  type="number"
                  min="0"
                  max="365"
                  value={forecastConfig.offset_days}
                  onChange={(e) => setForecastConfig({...forecastConfig, offset_days: parseInt(e.target.value) || 0})}
                />
              </div>

              <div className="config-item">
                <label>
                  Min Context Items
                  <span style={{fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px'}}>
                    - Minimum evidence items to use
                  </span>
                </label>
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={forecastConfig.min_context_items}
                  onChange={(e) => setForecastConfig({...forecastConfig, min_context_items: parseInt(e.target.value) || 1})}
                />
              </div>

              <div className="config-item">
                <label>
                  Forecast Mode
                  <span style={{fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px'}}>
                    - What information can the agent access?
                  </span>
                </label>
                <select
                  value={forecastConfig.mode}
                  onChange={(e) => setForecastConfig({...forecastConfig, mode: e.target.value})}
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
                <label style={{display: 'flex', alignItems: 'center', gap: '8px'}}>
                  <input
                    type="checkbox"
                    checked={forecastConfig.enable_causal_tools}
                    onChange={(e) => setForecastConfig({...forecastConfig, enable_causal_tools: e.target.checked})}
                    style={{width: '18px', height: '18px', margin: 0, accentColor: '#4CAF50'}}
                  />
                  Enable Causal Reasoning Tools
                  <span style={{fontSize: '12px', fontWeight: 'normal', color: '#888', marginLeft: '4px'}}>
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
          <div className="jobs-section">
            <h3>Recent Forecast Jobs</h3>

            {loadingJobs ? (
              <div className="loading">Loading jobs...</div>
            ) : jobs.length === 0 ? (
              <div className="no-jobs">No forecast jobs yet</div>
            ) : (
              <div className="jobs-list">
                {jobs.map(job => (
                  <div
                    key={job.job_id}
                    className={`job-item ${job.status}`}
                    onClick={() => job.status === 'completed' && fetchForecastResults(job.job_id)}
                  >
                    <div className="job-header">
                      <span className="job-status">{job.status}</span>
                      <span className="job-date">
                        {new Date(job.created_at).toLocaleString()}
                      </span>
                    </div>

                    {job.status === 'running' && (
                      <div className="job-progress">
                        <div className="progress-bar">
                          <div
                            className="progress-fill"
                            style={{width: `${(job.progress || 0) * 100}%`}}
                          />
                        </div>
                        <span className="progress-text">
                          {job.processed_count || 0} / {job.total_count || 0}
                        </span>
                      </div>
                    )}

                    {job.results && (
                      <div className="job-results">
                        <span>✓ {job.results.processed}</span>
                        {job.results.failed > 0 && <span>✗ {job.results.failed}</span>}
                        {job.results.skipped > 0 && <span>⊘ {job.results.skipped}</span>}
                        <span>⏱ {job.results.duration_seconds?.toFixed(1)}s</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Forecast Results Display */}
          {forecastResults && (
            <div className="forecast-results-section">
              <h3>Forecast Results</h3>
              {loadingResults ? (
                <div className="loading">Loading results...</div>
              ) : (
                <div className="results-content">
                  <pre>{JSON.stringify(forecastResults, null, 2)}</pre>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Main Content - Questions & Price History */}
        <div className="forecast-main-content">
          {/* Question Selection */}
          <div className="forecast-questions-panel">
          <div className="questions-header">
            <h3>Questions</h3>
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
        </div>
      </div>
    </div>
  );
};

export default ForecastPage;
