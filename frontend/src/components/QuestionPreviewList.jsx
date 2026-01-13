import React, { useState, useMemo } from 'react'
import './QuestionPreviewList.css'

/**
 * QuestionPreviewList - Display and select questions for saving
 *
 * Features:
 * - Multi-select with checkboxes
 * - Select all / clear all
 * - Filter by search text, domain, type
 * - Sort by difficulty, date
 * - Batch save selected
 */
function QuestionPreviewList({ questions, onSaveSelected, loading, source }) {
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [searchText, setSearchText] = useState('')
  const [domainFilter, setDomainFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [sortBy, setSortBy] = useState('difficulty')

  // Extract unique domains and types from questions (with safety check)
  const availableDomains = useMemo(() => {
    if (!Array.isArray(questions)) return ['all'];
    const domains = new Set(questions.map(q => q.domain))
    return ['all', ...Array.from(domains).sort()]
  }, [questions])

  const availableTypes = useMemo(() => {
    if (!Array.isArray(questions)) return ['all'];
    const types = new Set(questions.map(q => q.question_type))
    return ['all', ...Array.from(types).sort()]
  }, [questions])

  // Filter and sort questions
  const filteredQuestions = useMemo(() => {
    let filtered = Array.isArray(questions) ? questions : [];

    // Search filter
    if (searchText) {
      const search = searchText.toLowerCase()
      filtered = filtered.filter(q => {
        const text = q.question_text ? String(q.question_text).toLowerCase() : ''
        const id = q.id ? String(q.id).toLowerCase() : ''
        return text.includes(search) || id.includes(search)
      })
    }

    // Domain filter
    if (domainFilter !== 'all') {
      filtered = filtered.filter(q => q.domain === domainFilter)
    }

    // Type filter
    if (typeFilter !== 'all') {
      filtered = filtered.filter(q => q.question_type === typeFilter)
    }

    // Sort
    filtered = [...filtered].sort((a, b) => {
      switch (sortBy) {
        case 'difficulty':
          return b.difficulty - a.difficulty
        case 'date':
          if (!a.resolution_date) return 1
          if (!b.resolution_date) return -1
          return new Date(b.resolution_date) - new Date(a.resolution_date)
        case 'quality':
          return (b.quality_score || 0) - (a.quality_score || 0)
        default:
          return 0
      }
    })

    return filtered
  }, [questions, searchText, domainFilter, typeFilter, sortBy])

  const handleToggleSelect = (questionId) => {
    setSelectedIds(prev => {
      const newSet = new Set(prev)
      if (newSet.has(questionId)) {
        newSet.delete(questionId)
      } else {
        newSet.add(questionId)
      }
      return newSet
    })
  }

  const handleSelectAll = () => {
    setSelectedIds(new Set(filteredQuestions.map(q => q.id)))
  }

  const handleClearAll = () => {
    setSelectedIds(new Set())
  }

  const handleSave = () => {
    const selected = questions.filter(q => selectedIds.has(q.id))
    onSaveSelected(selected)
    setSelectedIds(new Set())
  }

  const selectedCount = selectedIds.size

  const safeQuestions = Array.isArray(questions) ? questions : [];
  if (safeQuestions.length === 0 && !loading) {
    return (
      <div className="preview-list-empty">
        <div className="empty-state">
          <div className="empty-icon">🔍</div>
          <h3>No questions yet</h3>
          <p>Configure filters and click "Fetch Questions" to see results</p>
        </div>
      </div>
    )
  }

  return (
    <div className="preview-list">
      <div className="preview-header">
        <h3>
          📋 Preview ({filteredQuestions.length} of {safeQuestions.length})
        </h3>
        {selectedCount > 0 && (
          <button
            className="save-button"
            onClick={handleSave}
            disabled={loading}
          >
            💾 Save {selectedCount} selected
          </button>
        )}
      </div>

      {safeQuestions.length > 0 && (
        <>
          {/* Filters and controls */}
          <div className="preview-controls">
            <div className="control-row">
              <input
                type="text"
                placeholder="🔍 Search questions..."
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                className="search-input"
                disabled={loading}
              />
            </div>

            <div className="control-row">
              <select
                value={domainFilter}
                onChange={(e) => setDomainFilter(e.target.value)}
                className="filter-select"
                disabled={loading}
              >
                {availableDomains.map(domain => (
                  <option key={domain} value={domain}>
                    {domain === 'all' ? 'All Domains' : domain}
                  </option>
                ))}
              </select>

              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="filter-select"
                disabled={loading}
              >
                {availableTypes.map(type => (
                  <option key={type} value={type}>
                    {type === 'all' ? 'All Types' : type}
                  </option>
                ))}
              </select>

              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="filter-select"
                disabled={loading}
              >
                <option value="difficulty">Sort by Difficulty</option>
                <option value="date">Sort by Date</option>
                <option value="quality">Sort by Quality</option>
              </select>
            </div>

            <div className="control-row">
              <button
                className="control-button"
                onClick={handleSelectAll}
                disabled={loading || filteredQuestions.length === 0}
              >
                ✓ Select All ({filteredQuestions.length})
              </button>
              <button
                className="control-button"
                onClick={handleClearAll}
                disabled={loading || selectedCount === 0}
              >
                ✕ Clear ({selectedCount})
              </button>
            </div>
          </div>

          {/* Question list */}
          <div className="preview-list-content">
            {filteredQuestions.map(question => (
              <div
                key={question.id}
                className={`question-preview-item ${selectedIds.has(question.id) ? 'selected' : ''}`}
              >
                <div className="question-checkbox">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(question.id)}
                    onChange={() => handleToggleSelect(question.id)}
                    disabled={loading}
                  />
                </div>

                <div className="question-content">
                  <div className="question-text">{question.question_text}</div>

                  <div className="question-meta">
                    <span className="meta-badge type-badge">
                      {question.question_type}
                    </span>
                    <span className="meta-badge domain-badge">
                      {question.domain}
                    </span>
                    <span className="meta-badge difficulty-badge">
                      Difficulty: {question.difficulty}/5
                    </span>
                    {question.quality_score && (
                      <span className="meta-badge quality-badge">
                        Quality: {(question.quality_score * 100).toFixed(0)}%
                      </span>
                    )}
                    {question.resolution_date && (
                      <span className="meta-badge date-badge">
                        Resolves: {new Date(question.resolution_date).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  {question.resolution_criteria && (
                    <div className="question-criteria">
                      <strong>Resolution Criteria:</strong> {question.resolution_criteria}
                    </div>
                  )}

                  {question.ground_truth !== null && question.ground_truth !== undefined && (
                    <div className="question-ground-truth">
                      <strong>Ground Truth:</strong>{' '}
                      <span className="ground-truth-value">
                        {typeof question.ground_truth === 'boolean'
                          ? question.ground_truth ? 'TRUE' : 'FALSE'
                          : question.ground_truth}
                      </span>
                    </div>
                  )}

                  {question.resolution_reasoning && (
                    <div className="question-reasoning">
                      <strong>Resolution Reasoning:</strong> {question.resolution_reasoning}
                    </div>
                  )}

                  {source === 'polymarket' && question.metadata?.market_slug && (
                    <div className="question-link">
                      <a
                        href={`https://polymarket.com/event/${question.metadata.market_slug}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        View on Polymarket →
                      </a>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default QuestionPreviewList
