import React, { useState, useEffect, useRef } from 'react'
import './ControlPanel.css'

const ControlPanel = ({ filters, onFilterChange, onRefresh, loading, questions, onQuestionFilter }) => {
  const [localFilters, setLocalFilters] = useState(filters)
  const [isExpanded, setIsExpanded] = useState(true)
  const [selectedQuestionId, setSelectedQuestionId] = useState('')
  const [questionSearch, setQuestionSearch] = useState('')
  const [showQuestionList, setShowQuestionList] = useState(false)
  const questionSearchRef = useRef(null)

  const handleApply = () => {
    onFilterChange(localFilters)
  }

  const handleReset = () => {
    const defaultFilters = {
      maxNodes: 100,
      maxEdges: 500,
      minEdgeWeight: 0,
    }
    setLocalFilters(defaultFilters)
    onFilterChange(defaultFilters)
    setSelectedQuestionId('')
    setQuestionSearch('')
    if (onQuestionFilter) {
      onQuestionFilter(null)
    }
  }

  const handleQuestionSelect = (questionId) => {
    setSelectedQuestionId(questionId)
    const question = questions.find(q => q.id === questionId)
    if (question) {
      setQuestionSearch(question.question_text)
    }
    setShowQuestionList(false)
    if (onQuestionFilter) {
      onQuestionFilter(questionId || null)
    }
  }

  const handleQuestionSearchChange = (e) => {
    setQuestionSearch(e.target.value)
    setShowQuestionList(true)
    // If search is cleared, reset filter
    if (!e.target.value) {
      setSelectedQuestionId('')
      if (onQuestionFilter) {
        onQuestionFilter(null)
      }
    }
  }

  const handleClearQuestion = () => {
    setQuestionSearch('')
    setSelectedQuestionId('')
    setShowQuestionList(false)
    if (onQuestionFilter) {
      onQuestionFilter(null)
    }
  }

  // Filter questions based on search
  const filteredQuestions = questions.filter(q =>
    q.question_text.toLowerCase().includes(questionSearch.toLowerCase())
  )

  // Close question list when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (questionSearchRef.current && !questionSearchRef.current.contains(event.target)) {
        setShowQuestionList(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [])

  return (
    <div className={`control-panel ${isExpanded ? 'expanded' : 'collapsed'}`}>
      <div className="panel-header">
        <h3>Controls</h3>
        <button
          className="toggle-btn"
          onClick={() => setIsExpanded(!isExpanded)}
        >
          {isExpanded ? '◀' : '▶'}
        </button>
      </div>

      {isExpanded && (
        <div className="panel-content">
          <div className="filter-section question-search-section" ref={questionSearchRef}>
            <label>Filter by Question</label>
            <div className="question-search-container">
              <input
                type="text"
                placeholder="Search questions..."
                value={questionSearch}
                onChange={handleQuestionSearchChange}
                onFocus={() => setShowQuestionList(true)}
                disabled={loading}
                className="question-search-input"
              />
              {questionSearch && (
                <button
                  className="clear-search-btn"
                  onClick={handleClearQuestion}
                  title="Clear search"
                >
                  ×
                </button>
              )}
            </div>
            {showQuestionList && questionSearch && (
              <div className="question-list">
                {filteredQuestions.length > 0 ? (
                  filteredQuestions.slice(0, 10).map(q => (
                    <div
                      key={q.id}
                      className={`question-item ${selectedQuestionId === q.id ? 'selected' : ''}`}
                      onClick={() => handleQuestionSelect(q.id)}
                    >
                      <div className="question-text">{q.question_text}</div>
                      <div className="question-meta">
                        <span className="question-domain">{q.domain}</span>
                        <span className="question-difficulty">Difficulty: {q.difficulty}/5</span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="question-item no-results">No questions found</div>
                )}
                {filteredQuestions.length > 10 && (
                  <div className="question-item more-results">
                    {filteredQuestions.length - 10} more... (refine search)
                  </div>
                )}
              </div>
            )}
            <small>
              {selectedQuestionId
                ? 'Showing all extracted events + causal neighborhood (depth 2)'
                : 'Search and select a question to filter the graph'}
            </small>
          </div>

          <div className="filter-section">
            <label>Max Nodes: {localFilters.maxNodes}</label>
            <input
              type="range"
              min="10"
              max="1000"
              step="10"
              value={localFilters.maxNodes}
              onChange={(e) =>
                setLocalFilters({ ...localFilters, maxNodes: parseInt(e.target.value) })
              }
            />
          </div>

          <div className="filter-section">
            <label>Max Edges: {localFilters.maxEdges}</label>
            <input
              type="range"
              min="10"
              max="5000"
              step="50"
              value={localFilters.maxEdges}
              onChange={(e) =>
                setLocalFilters({ ...localFilters, maxEdges: parseInt(e.target.value) })
              }
            />
          </div>

          <div className="filter-section">
            <label>Min Edge Weight: {localFilters.minEdgeWeight.toFixed(2)}</label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={localFilters.minEdgeWeight}
              onChange={(e) =>
                setLocalFilters({ ...localFilters, minEdgeWeight: parseFloat(e.target.value) })
              }
            />
          </div>

          <div className="button-group">
            <button onClick={handleApply} disabled={loading}>
              Apply Filters
            </button>
            <button onClick={handleReset} disabled={loading}>
              Reset
            </button>
            <button onClick={onRefresh} disabled={loading}>
              Refresh
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default ControlPanel
