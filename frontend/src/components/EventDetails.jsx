import React, { useState, useEffect } from 'react'
import { fetchEventArticles, fetchEventQuestions } from '../api/graphApi'
import './EventDetails.css'

const EventDetails = ({ node, onClose, onShowNeighborhood }) => {
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
        <h3>{node.name}</h3>
        <button className="close-btn" onClick={onClose}>
          ×
        </button>
      </div>

      <div className="details-content">
        <div className="detail-row">
          <span className="label">Type:</span>
          <span className="value">{node.type}</span>
        </div>

        <div className="detail-row">
          <span className="label">Importance:</span>
          <span className="value">{node.properties?.importance?.toFixed(2) || 'N/A'}</span>
        </div>

        {node.properties?.description && (
          <div className="detail-row">
            <span className="label">Description:</span>
            <span className="value">{node.properties.description}</span>
          </div>
        )}

        {node.properties?.occurred_date && (
          <div className="detail-row">
            <span className="label">Occurred:</span>
            <span className="value">{formatDate(node.properties.occurred_date)}</span>
          </div>
        )}

        {node.properties?.predicted_date && (
          <div className="detail-row">
            <span className="label">Predicted:</span>
            <span className="value">{formatDate(node.properties.predicted_date)}</span>
          </div>
        )}

        {node.properties?.event_type && (
          <div className="detail-row">
            <span className="label">Event Type:</span>
            <span className="value">{node.properties.event_type}</span>
          </div>
        )}

        {node.properties?.status && (
          <div className="detail-row">
            <span className="label">Status:</span>
            <span className="value">{node.properties.status}</span>
          </div>
        )}

        <div className="detail-row">
          <span className="label">Causes:</span>
          <span className="value">{node.properties?.num_causes || 0} events</span>
        </div>

        <div className="detail-row">
          <span className="label">Caused by:</span>
          <span className="value">{node.properties?.num_caused_by || 0} events</span>
        </div>

        <div className="expandable-section">
          <button
            className="section-toggle"
            onClick={() => setShowArticles(!showArticles)}
          >
            <span className="toggle-icon">{showArticles ? '▼' : '▶'}</span>
            Related Articles {articlesLoaded ? `(${articles.length})` : ''}
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
                    <div key={article.id} className="article-item">
                      <div className="article-header">
                        <h4 className="article-title">{article.title}</h4>
                        <span className="article-date">{formatDate(article.published_date)}</span>
                      </div>
                      <div className="article-source">{article.source}</div>
                      <div className="article-content">{truncateText(article.content)}</div>
                      {article.url && (
                        <a
                          href={article.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="article-link"
                        >
                          Read more →
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
            className="section-toggle"
            onClick={() => setShowQuestions(!showQuestions)}
          >
            <span className="toggle-icon">{showQuestions ? '▼' : '▶'}</span>
            Related Questions {questionsLoaded ? `(${questions.length})` : ''}
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
                    <div key={question.id} className="question-item">
                      <div className="question-text">{question.question_text}</div>
                      <div className="question-meta">
                        <span className="question-domain">{question.domain}</span>
                        <span className="question-type">{question.question_type}</span>
                        <span className="question-difficulty">Difficulty: {question.difficulty}/5</span>
                      </div>
                      {question.resolution_date && (
                        <div className="question-resolution">
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

        <div className="button-group">
          <button onClick={() => onShowNeighborhood(node.id, 1)}>
            Show Immediate Links
          </button>
          <button onClick={() => onShowNeighborhood(node.id, 2)}>
            Show 2-Hop Neighborhood
          </button>
        </div>
      </div>
    </div>
  )
}

export default EventDetails
