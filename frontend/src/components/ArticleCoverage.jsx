import React, { useState, useEffect } from 'react'
import './ArticleCoverage.css'

/**
 * ArticleCoverage - Display article coverage analysis for a question
 */
function ArticleCoverage({ questionId }) {
  const [coverage, setCoverage] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!questionId) {
      setCoverage(null)
      return
    }

    setLoading(true)
    setError(null)

    fetch(`/api/questions/${questionId}/article_coverage`)
      .then(res => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`)
        }
        return res.json()
      })
      .then(data => {
        setCoverage(data)
      })
      .catch(err => {
        console.error('Error fetching article coverage:', err)
        setError(err.message)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [questionId])

  if (!questionId) {
    return null
  }

  if (loading) {
    return (
      <div className="article-coverage-container">
        <div className="coverage-loading">
          ⏳ Loading article coverage analysis...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="article-coverage-container">
        <div className="coverage-error">
          ⚠️ Error loading article coverage: {error}
        </div>
      </div>
    )
  }

  if (!coverage) {
    return null
  }

  const { article_count, timeline, sources, gaps, quality, recommendation } = coverage

  // Determine quality badge color
  const getQualityColor = (score) => {
    if (score >= 0.8) return '#4CAF50'
    if (score >= 0.6) return '#FFA726'
    if (score >= 0.4) return '#FF9800'
    return '#F44336'
  }

  return (
    <div className="article-coverage-container">
      <div className="coverage-header" onClick={() => setExpanded(!expanded)}>
        <div className="coverage-title">
          <span className="coverage-icon">📊</span>
          <span>Article Coverage Analysis</span>
          <span className="article-count-badge">{article_count} articles</span>
        </div>
        <div className="coverage-summary">
          <div className="quality-badge" style={{ backgroundColor: getQualityColor(quality.score) }}>
            Quality: {(quality.score * 100).toFixed(0)}%
          </div>
          <button className="expand-button">
            {expanded ? '▼' : '▶'}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="coverage-details">
          {article_count === 0 ? (
            <div className="no-articles">
              <p>No articles collected yet for this question.</p>
              <p className="recommendation-text">{recommendation}</p>
            </div>
          ) : (
            <>
              {/* Quality Metrics */}
              <div className="metrics-grid">
                <div className="metric-card">
                  <div className="metric-label">Volume</div>
                  <div className="metric-value">{(quality.volume_score * 100).toFixed(0)}%</div>
                  <div className="metric-detail">{article_count} articles</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Diversity</div>
                  <div className="metric-value">{(quality.diversity_score * 100).toFixed(0)}%</div>
                  <div className="metric-detail">{sources.unique_sources} sources</div>
                </div>
                <div className="metric-card">
                  <div className="metric-label">Coverage</div>
                  <div className="metric-value">{(quality.coverage_score * 100).toFixed(0)}%</div>
                  <div className="metric-detail">{gaps.length} gaps</div>
                </div>
              </div>

              {/* Timeline */}
              {timeline.has_dates && (
                <div className="section">
                  <h4>Timeline Distribution</h4>
                  <div className="timeline-info">
                    <div className="timeline-range">
                      {new Date(timeline.earliest).toLocaleDateString()} → {new Date(timeline.resolution_date).toLocaleDateString()}
                    </div>
                    <div className="timeline-span">{timeline.span_days} days</div>
                  </div>
                  {timeline.monthly && Object.keys(timeline.monthly).length > 0 && (
                    <div className="monthly-chart">
                      {Object.entries(timeline.monthly).sort().map(([month, count]) => {
                        const maxCount = Math.max(...Object.values(timeline.monthly))
                        const percentage = (count / maxCount) * 100
                        return (
                          <div key={month} className="month-row">
                            <div className="month-label">{month}</div>
                            <div className="month-bar-container">
                              <div
                                className="month-bar"
                                style={{ width: `${percentage}%` }}
                                title={`${count} articles`}
                              />
                            </div>
                            <div className="month-count">{count}</div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Gaps */}
              {gaps.length > 0 && (
                <div className="section">
                  <h4>Timeline Gaps (&gt;7 days)</h4>
                  <div className="gaps-list">
                    {gaps.slice(0, 5).map((gap, idx) => (
                      <div key={idx} className="gap-item">
                        <span className="gap-icon">⚠️</span>
                        <div className="gap-info">
                          <div className="gap-dates">
                            {new Date(gap.start).toLocaleDateString()} → {new Date(gap.end).toLocaleDateString()}
                          </div>
                          <div className="gap-duration">{gap.days} days</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Top Sources */}
              {sources.top_sources && sources.top_sources.length > 0 && (
                <div className="section">
                  <h4>Top Sources</h4>
                  <div className="sources-list">
                    {sources.top_sources.map(([source, count], idx) => (
                      <div key={idx} className="source-item">
                        <span className="source-bullet">•</span>
                        <span className="source-name">{source}</span>
                        <span className="source-count">{count} {count === 1 ? 'article' : 'articles'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recommendation */}
              {recommendation && (
                <div className="section recommendation-section">
                  <div className="recommendation-text">
                    {recommendation.split('\n').map((line, idx) => (
                      <p key={idx}>{line}</p>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default ArticleCoverage
