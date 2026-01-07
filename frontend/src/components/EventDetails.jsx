import React, { useState, useEffect, memo } from 'react'
import { fetchEventArticles, fetchEventQuestions } from '../api/graphApi'
import './EventDetails.css'

const EventDetails = memo(function EventDetails({ node, onClose, onShowNeighborhood }) {
  const [articles, setArticles] = useState([])
  const [questions, setQuestions] = useState([])
  const [loadingArticles, setLoadingArticles] = useState(false)
  const [loadingQuestions, setLoadingQuestions] = useState(false)
  const [showArticles, setShowArticles] = useState(false)
  const [showQuestions, setShowQuestions] = useState(false)
  const [articlesLoaded, setArticlesLoaded] = useState(false)
  const [questionsLoaded, setQuestionsLoaded] = useState(false)

  if (!node) return null

  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown'
    return new Date(dateString).toLocaleDateString()
  }

  const truncateText = (text, maxLength = 150) => {
    if (!text) return ''
    if (text.length <= maxLength) return text
    return text.substring(0, maxLength) + '...'
  }

  // Reset state when node changes
  useEffect(() => {
    setArticles([])
    setQuestions([])
    setShowArticles(false)
    setShowQuestions(false)
    setArticlesLoaded(false)
    setQuestionsLoaded(false)
  }, [node.id])

  // Load articles when expanded
  useEffect(() => {
    if (showArticles && !articlesLoaded && !loadingArticles) {
      setLoadingArticles(true)
      fetchEventArticles(node.id)
        .then(data => {
          console.log('Fetched articles for event:', node.id, data)
          setArticles(data.articles || [])
          setArticlesLoaded(true)
        })
        .catch(error => {
          console.error('Failed to load articles:', error)
          setArticlesLoaded(true)
        })
        .finally(() => {
          setLoadingArticles(false)
        })
    }
  }, [showArticles, articlesLoaded, loadingArticles, node.id])

  // Load questions when expanded
  useEffect(() => {
    if (showQuestions && !questionsLoaded && !loadingQuestions) {
      setLoadingQuestions(true)
      fetchEventQuestions(node.id)
        .then(data => {
          console.log('Fetched questions for event:', node.id, data)
          setQuestions(data.questions || [])
          setQuestionsLoaded(true)
        })
        .catch(error => {
          console.error('Failed to load questions:', error)
          setQuestionsLoaded(true)
        })
        .finally(() => {
          setLoadingQuestions(false)
        })
    }
  }, [showQuestions, questionsLoaded, loadingQuestions, node.id])

  return (
    <div className="event-details">
      <div className="details-header">
        <div className="header-top">
          <span
            className="node-type-badge"
            style={{
              textTransform: 'capitalize',
              backgroundColor: '#e7f3ff',
              color: '#2563eb',
              border: '1px solid #bfdbfe',
              fontSize: '0.75rem',
              fontWeight: '600',
              padding: '0.35rem 0.85rem',
              borderRadius: '6px',
              letterSpacing: '0.025em'
            }}
          >
            {node.domain || 'General'}
          </span>
          <button className="close-btn" onClick={onClose} aria-label="Close details">
            ×
          </button>
        </div>
        <h3 style={{
          fontSize: '1.25rem',
          fontWeight: '600',
          lineHeight: '1.5',
          marginTop: '0.875rem',
          color: '#1f2937'
        }}>
          {node.name}
        </h3>
      </div>

      <div className="details-content">
        <div className="metrics-grid" style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
          <div className="metric-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '0.75rem', borderBottom: '1px solid #e9ecef' }}>
            <span className="metric-label" style={{ fontSize: '0.8125rem', color: '#6c757d', fontWeight: '500' }}>Event Type</span>
            <span className="metric-value" style={{ textAlign: 'right', wordBreak: 'break-word', maxWidth: '65%', fontSize: '0.9375rem', fontWeight: '600', color: '#212529', textTransform: 'capitalize' }}>
              {node.properties?.event_type || node.event_type || 'N/A'}
            </span>
          </div>

          {(node.properties?.occurred_date || node.properties?.predicted_date) && (
            <div className="metric-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '0.75rem', borderBottom: '1px solid #e9ecef' }}>
              <span className="metric-label" style={{ fontSize: '0.8125rem', color: '#6c757d', fontWeight: '500' }}>Date</span>
              <span className="metric-value" style={{ textAlign: 'right', wordBreak: 'break-word', maxWidth: '65%', fontSize: '0.9375rem', fontWeight: '600', color: '#212529' }}>
                {formatDate(node.properties?.occurred_date || node.properties?.predicted_date)}
              </span>
            </div>
          )}

          {node.properties?.status && (
            <div className="metric-item" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingBottom: '0.75rem', borderBottom: '1px solid #e9ecef' }}>
              <span className="metric-label" style={{ fontSize: '0.8125rem', color: '#6c757d', fontWeight: '500' }}>Status</span>
              <span className="metric-value status-value" style={{ textAlign: 'right', wordBreak: 'break-word', maxWidth: '65%', fontSize: '0.9375rem', fontWeight: '600', color: '#212529', textTransform: 'capitalize' }}>
                {node.properties.status}
              </span>
            </div>
          )}
        </div>

        {node.properties?.description && (
          <div className="description-block">
            <h4>Description</h4>
            <p>{node.properties.description}</p>
          </div>
        )}

        <div className="expandable-section">
          <button
            className={`section-toggle ${showArticles ? 'active' : ''}`}
            onClick={() => setShowArticles(!showArticles)}
          >
            <span className="toggle-text">Related Articles</span>
            <span className="toggle-meta">
              {articlesLoaded ? articles.length : ''}
              <span className="toggle-icon">{showArticles ? '−' : '+'}</span>
            </span>
          </button>

          {showArticles && (
            <div className="section-content">
              {loadingArticles ? (
                <div className="loading-message">Loading articles...</div>
              ) : articles.length === 0 ? (
                <div className="empty-message">No articles found</div>
              ) : (
                <div className="articles-list">
                  {articles.map(article => (
                    <div key={article.id} className="article-card">
                      <div className="article-header">
                        <h4 className="article-title">{article.title}</h4>
                        <span className="article-date">{formatDate(article.published_date)}</span>
                      </div>
                      <div className="article-source-badge">{article.source}</div>
                      <p className="article-excerpt">{truncateText(article.content)}</p>
                      {article.url && (
                        <a
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="article-link"
                        >
                          Read Source ↗
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="expandable-section">
          <button
            className={`section-toggle ${showQuestions ? 'active' : ''}`}
            onClick={() => setShowQuestions(!showQuestions)}
          >
            <span className="toggle-text">Related Questions</span>
            <span className="toggle-meta">
              {questionsLoaded ? questions.length : ''}
              <span className="toggle-icon">{showQuestions ? '−' : '+'}</span>
            </span>
          </button>

          {showQuestions && (
            <div className="section-content">
              {loadingQuestions ? (
                <div className="loading-message">Loading questions...</div>
              ) : questions.length === 0 ? (
                <div className="empty-message">No questions found</div>
              ) : (
                <div className="questions-list">
                  {questions.map(question => (
                    <div key={question.id} className="question-card">
                      <div className="question-text">{question.question_text}</div>
                      <div className="question-tags">
                        <span className="tag domain">{question.domain}</span>
                        <span className="tag difficulty">Diff: {question.difficulty}/5</span>
                      </div>
                      {question.resolution_date && (
                        <div className="question-footer">
                          Resolution: {formatDate(question.resolution_date)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="actions-footer">
          <h4>Explore Neighborhood</h4>
          <div className="button-group">
            <button className="action-btn primary" onClick={() => onShowNeighborhood(node.id, 1)}>
              Immediate Links
            </button>
            <button className="action-btn secondary" onClick={() => onShowNeighborhood(node.id, 2)}>
              2-Hop Network
            </button>
          </div>
        </div>
      </div>
    </div>
  )
})

export default EventDetails
