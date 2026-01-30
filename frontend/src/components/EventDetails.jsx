import React, { useState, useEffect, memo, useRef } from 'react'
import { fetchEventArticles, fetchEventQuestions, fetchEventImpacts, fetchOutcomeImpacts } from '../api/graphApi'
import './EventDetails.css'

const EventDetails = memo(function EventDetails({ node, onClose, onShowNeighborhood }) {
  const [articles, setArticles] = useState([])
  const [questions, setQuestions] = useState([])
  const [impacts, setImpacts] = useState([])
  const [loadingArticles, setLoadingArticles] = useState(false)
  const [loadingQuestions, setLoadingQuestions] = useState(false)
  const [loadingImpacts, setLoadingImpacts] = useState(false)
  const [showArticles, setShowArticles] = useState(false)
  const [showQuestions, setShowQuestions] = useState(false)
  const [showImpacts, setShowImpacts] = useState(false)
  const [articlesLoaded, setArticlesLoaded] = useState(false)
  const [questionsLoaded, setQuestionsLoaded] = useState(false)
  const [impactsLoaded, setImpactsLoaded] = useState(false)

  // Dragging state
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragOffset = useRef({ x: 0, y: 0 })

  if (!node) return null

  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown'
    return new Date(dateString).toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
  }

  const truncateText = (text, maxLength = 150) => {
    if (!text) return ''
    if (text.length <= maxLength) return text
    return text.substring(0, maxLength) + '...'
  }

  // Initialize position when node changes (Smart Positioning)
  useEffect(() => {
    const screenX = node._screenX || 0
    const screenY = node._screenY || 0

    // Constants
    const POPUP_WIDTH = 320
    const POPUP_EST_HEIGHT = 400
    const PADDING = 20
    const WINDOW_W = window.innerWidth
    const WINDOW_H = window.innerHeight

    // POSITIONING STRATEGY:
    // User requested "Right of the event node".
    // 1. Default X: To the right of the node (node center + offset)
    // 2. Default Y: Align top of popup with top of node (node center - offset)

    let x = screenX + 60
    let y = screenY - 100

    // Clamp X (Right Edge)
    // If it goes off-screen right, shift it left just enough to fit
    if (x + POPUP_WIDTH > WINDOW_W - PADDING) {
      x = WINDOW_W - POPUP_WIDTH - PADDING
    }
    // Clamp X (Left Edge)
    x = Math.max(PADDING, x)

    // Clamp Y (Bottom Edge)
    if (y + POPUP_EST_HEIGHT > WINDOW_H - PADDING) {
      y = WINDOW_H - POPUP_EST_HEIGHT - PADDING
    }
    // Clamp Y (Top Edge)
    y = Math.max(PADDING + 60, y) // +60 for header clear

    setPosition({ x, y })
  }, [node.id, node._screenX, node._screenY])

  // Handle dragging
  useEffect(() => {
    if (!isDragging) return

    const handleMouseMove = (e) => {
      setPosition({
        x: e.clientX - dragOffset.current.x,
        y: e.clientY - dragOffset.current.y
      })
    }

    const handleMouseUp = () => {
      setIsDragging(false)
    }

    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)

    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging])

  const handleMouseDown = (e) => {
    // Only allow dragging from header (excluding close button)
    if (e.target.closest('.close-btn')) return

    setIsDragging(true)
    dragOffset.current = {
      x: e.clientX - position.x,
      y: e.clientY - position.y
    }
  }

  // Reset state when node changes
  useEffect(() => {
    setArticles([])
    setQuestions([])
    setImpacts([])
    setShowArticles(false)
    setShowQuestions(false)
    setShowImpacts(false)
    setArticlesLoaded(false)
    setQuestionsLoaded(false)
    setImpactsLoaded(false)
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

  // Load impacts when expanded (for all nodes)
  useEffect(() => {
    if (showImpacts && !impactsLoaded && !loadingImpacts) {
      setLoadingImpacts(true)

      const fetchPromise = node.isOutcome
        ? fetchOutcomeImpacts(node.id) // Get incoming impacts for outcomes
        : fetchEventImpacts(node.id)   // Get outgoing impacts for regular events

      fetchPromise
        .then(data => {
          console.log('Fetched impacts for event:', node.id, data)
          setImpacts(data || [])
          setImpactsLoaded(true)
        })
        .catch(error => {
          console.error('Failed to load impacts:', error)
          setImpactsLoaded(true)
        })
        .finally(() => {
          setLoadingImpacts(false)
        })
    }
  }, [showImpacts, impactsLoaded, loadingImpacts, node.id, node.isOutcome])

  return (
    <div className="event-details" style={{
      maxWidth: '320px',
      maxHeight: '80vh',
      display: 'flex',
      flexDirection: 'column',
      // Fixed positioning relative to viewport
      position: 'fixed',
      left: position.x,
      top: position.y,
      zIndex: 1000,
      transform: 'translate(0, 0)',
      boxShadow: '0 8px 30px rgba(0,0,0,0.2)',
      borderRadius: '8px'
    }}>
      <div
        className="details-header"
        onMouseDown={handleMouseDown}
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid #eee',
          cursor: isDragging ? 'grabbing' : 'grab',
          userSelect: 'none'
        }}
      >
        <div className="header-top" style={{ marginBottom: '8px' }}>
          <span
            className="node-type-badge"
            style={{
              textTransform: 'capitalize',
              backgroundColor: '#e7f3ff',
              color: '#2563eb',
              border: '1px solid #bfdbfe',
              fontSize: '0.7rem',
              fontWeight: '600',
              padding: '2px 8px',
              borderRadius: '12px',
              letterSpacing: '0.025em'
            }}
          >
            {node.domain || 'General'}
          </span>
          <button className="close-btn" onClick={onClose} aria-label="Close details" style={{ fontSize: '1.2rem', padding: '4px' }}>
            ×
          </button>
        </div>
        <h3 style={{
          fontSize: '1.1rem',
          fontWeight: '600',
          lineHeight: '1.4',
          margin: 0,
          color: '#111827'
        }}>
          {node.name}
        </h3>
      </div>

      <div className="details-content" style={{ padding: '16px 20px', overflowY: 'auto' }}>
        {/* Compact Metrics Row */}
        <div className="metrics-row" style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '16px',
          fontSize: '0.8rem',
          color: '#4b5563',
          marginBottom: '16px',
          paddingBottom: '12px',
          borderBottom: '1px solid #f3f4f6'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span>📅</span>
            <span style={{ fontWeight: '500' }}>
              {formatDate(node.properties?.occurred_date || node.properties?.predicted_date)}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span>🏷️</span>
            <span style={{ textTransform: 'capitalize' }}>
              {node.properties?.event_type || node.event_type || 'Event'}
            </span>
          </div>

          {node.properties?.status && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span>
                {node.properties.status === 'occurred' ? '✅' :
                  node.properties.status === 'predicted' ? '🔮' : 'ℹ️'}
              </span>
              <span style={{ textTransform: 'capitalize' }}>
                {node.properties.status}
              </span>
            </div>
          )}
        </div>

        {node.properties?.description && (
          <div className="description-block" style={{ marginBottom: '16px' }}>
            <p style={{
              fontSize: '0.9rem',
              lineHeight: '1.5',
              color: '#374151',
              margin: 0
            }}>
              {node.properties.description}
            </p>
          </div>
        )}

        <div className="expandable-section">
          <button
            className={`section-toggle ${showArticles ? 'active' : ''}`}
            onClick={() => setShowArticles(!showArticles)}
            style={{ padding: '8px 12px', fontSize: '0.9rem' }}
          >
            <span className="toggle-text">Related Articles</span>
            <span className="toggle-meta" style={{ fontSize: '0.8rem' }}>
              {articlesLoaded ? articles.length : ''}
              <span className="toggle-icon">{showArticles ? '−' : '+'}</span>
            </span>
          </button>

          {showArticles && (
            <div className="section-content">
              {loadingArticles ? (
                <div className="loading-message">Loading...</div>
              ) : articles.length === 0 ? (
                <div className="empty-message">No articles</div>
              ) : (
                <div className="articles-list">
                  {articles.map(article => (
                    <div key={article.id} className="article-card" style={{ padding: '10px' }}>
                      <div className="article-header">
                        <h4 className="article-title" style={{ fontSize: '0.9rem' }}>{article.title}</h4>
                        <span className="article-date" style={{ fontSize: '0.75rem' }}>{formatDate(article.published_date)}</span>
                      </div>
                      <div className="article-source-badge" style={{ fontSize: '0.7rem' }}>{article.source}</div>
                      <p className="article-excerpt" style={{ fontSize: '0.8rem', marginTop: '4px' }}>{truncateText(article.content)}</p>
                      {article.url && (
                        <a
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="article-link"
                          style={{ fontSize: '0.8rem' }}
                        >
                          Source ↗
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
            style={{ padding: '8px 12px', fontSize: '0.9rem' }}
          >
            <span className="toggle-text">Related Questions</span>
            <span className="toggle-meta" style={{ fontSize: '0.8rem' }}>
              {questionsLoaded ? questions.length : ''}
              <span className="toggle-icon">{showQuestions ? '−' : '+'}</span>
            </span>
          </button>

          {showQuestions && (
            <div className="section-content">
              {loadingQuestions ? (
                <div className="loading-message">Loading...</div>
              ) : questions.length === 0 ? (
                <div className="empty-message">No questions</div>
              ) : (
                <div className="questions-list">
                  {questions.map(question => (
                    <div key={question.id} className="question-card" style={{ padding: '10px' }}>
                      <div className="question-text" style={{ fontSize: '0.9rem' }}>{question.question_text}</div>
                      <div className="question-tags">
                        <span className="tag domain" style={{ fontSize: '0.7rem' }}>{question.domain}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Outcome Impacts - shown for all nodes that have impacts */}
        <div className="expandable-section">
          <button
            className={`section-toggle ${showImpacts ? 'active' : ''}`}
            onClick={() => setShowImpacts(!showImpacts)}
            style={{ padding: '8px 12px', fontSize: '0.9rem' }}
          >
            <span className="toggle-text">
              {node.isOutcome ? '⭐ Impacted By' : '🎯 Impact on Outcome'}
            </span>
            <span className="toggle-meta" style={{ fontSize: '0.8rem' }}>
              {impactsLoaded ? impacts.length : ''}
              <span className="toggle-icon">{showImpacts ? '−' : '+'}</span>
            </span>
          </button>

          {showImpacts && (
            <div className="section-content">
              {loadingImpacts ? (
                <div className="loading-message">Loading...</div>
              ) : impacts.length === 0 ? (
                <div className="empty-message">No impacts</div>
              ) : (
                <div className="impacts-list">
                  {impacts.map((impact, index) => {
                    const getDirectionInfo = (direction) => {
                      switch (direction) {
                        case 'positive':
                          return { icon: '↗', color: '#22c55e', label: 'Positive' }
                        case 'negative':
                          return { icon: '↘', color: '#ef4444', label: 'Negative' }
                        case 'mixed':
                          return { icon: '↔', color: '#a855f7', label: 'Mixed' }
                        case 'neutral':
                          return { icon: '→', color: '#94a3b8', label: 'Neutral' }
                        default:
                          return { icon: '?', color: '#6c757d', label: 'Unknown' }
                      }
                    }

                    const dirInfo = getDirectionInfo(impact.properties?.impact_direction)
                    const magnitude = impact.properties?.impact_magnitude || 0
                    const confidence = impact.properties?.confidence || 0
                    const reasoning = impact.properties?.reasoning || 'No reasoning'

                    return (
                      <div key={index} className="impact-item" style={{
                        padding: '10px',
                        marginBottom: '8px',
                        border: '1px solid #e0e0e0',
                        borderRadius: '6px',
                        backgroundColor: '#fff'
                      }}>
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          marginBottom: '6px'
                        }}>
                          <div style={{
                            width: '24px',
                            height: '24px',
                            borderRadius: '50%',
                            backgroundColor: dirInfo.color,
                            color: '#fff',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '12px',
                            fontWeight: '600'
                          }}>
                            {dirInfo.icon}
                          </div>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: '0.85rem', fontWeight: '600', color: '#333' }}>
                              {dirInfo.label} Impact
                            </div>
                            <div style={{ fontSize: '0.75rem', color: '#6c757d' }}>
                              Mag: {(magnitude * 100).toFixed(0)}% • Conf: {(confidence * 100).toFixed(0)}%
                            </div>
                          </div>
                        </div>
                        <div style={{
                          fontSize: '0.8rem',
                          color: '#495057',
                          lineHeight: '1.4',
                          padding: '6px',
                          backgroundColor: '#f8f9fa',
                          borderRadius: '4px'
                        }}>
                          {reasoning}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="actions-footer" style={{ marginTop: '16px' }}>
          <h4 style={{ fontSize: '0.8rem', marginBottom: '8px', color: '#6b7280' }}>Explore Neighborhood</h4>
          <div className="button-group">
            <button className="action-btn primary" onClick={() => onShowNeighborhood(node.id, 1)} style={{ fontSize: '0.8rem', padding: '6px 12px' }}>
              Immediate
            </button>
            <button className="action-btn secondary" onClick={() => onShowNeighborhood(node.id, 2)} style={{ fontSize: '0.8rem', padding: '6px 12px' }}>
              2-Hop
            </button>
          </div>
        </div>
      </div>
    </div>
  )
})

export default EventDetails
