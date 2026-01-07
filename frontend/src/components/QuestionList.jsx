import React, { useState, useEffect, useMemo, memo } from 'react'
import QuestionEditModal from './QuestionEditModal'
import QuestionStatistics from './QuestionStatistics'
import { useDebounce } from '../hooks/useDebounce'
import './QuestionList.css'

const QuestionList = memo(function QuestionList({
  questions,
  selectedQuestionId,
  onQuestionSelect,
  onClose,
  multiSelectMode = false,
  onQuestionsSelected = null,
  onQuestionUpdated = null,
  onQuestionDeleted = null
}) {
  const [searchTerm, setSearchTerm] = useState('')
  const debouncedSearchTerm = useDebounce(searchTerm, 300)
  const [domainFilter, setDomainFilter] = useState('all')
  const [difficultyFilter, setDifficultyFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [editingQuestion, setEditingQuestion] = useState(null)
  const [deletingQuestionId, setDeletingQuestionId] = useState(null)

  // Extract unique values for filters
  const domains = useMemo(() => {
    const domainSet = new Set(questions.map(q => q.domain))
    return Array.from(domainSet).sort()
  }, [questions])

  const sources = useMemo(() => {
    const sourceSet = new Set(questions.map(q => q.source || 'unknown'))
    return Array.from(sourceSet).sort()
  }, [questions])

  // Filter questions based on all criteria
  const filteredQuestions = useMemo(() => {
    return questions.filter(q => {
      // Search term (debounced for better performance)
      if (debouncedSearchTerm && !q.question_text.toLowerCase().includes(debouncedSearchTerm.toLowerCase())) {
        return false
      }

      // Domain filter
      if (domainFilter !== 'all' && q.domain !== domainFilter) {
        return false
      }

      // Difficulty filter
      if (difficultyFilter !== 'all' && q.difficulty !== parseInt(difficultyFilter)) {
        return false
      }

      // Source filter
      const questionSource = q.source || 'unknown'
      if (sourceFilter !== 'all' && questionSource !== sourceFilter) {
        return false
      }

      return true
    })
  }, [questions, debouncedSearchTerm, domainFilter, difficultyFilter, sourceFilter])

  const handleClearFilters = () => {
    setSearchTerm('')
    setDomainFilter('all')
    setDifficultyFilter('all')
    setSourceFilter('all')
  }

  // Show "Clear" button immediately when user types (before debounce delay)
  const hasActiveFilters = searchTerm || domainFilter !== 'all' || difficultyFilter !== 'all' || sourceFilter !== 'all'

  // Multi-select handlers
  const toggleSelection = (id, event) => {
    if (!multiSelectMode) {
      onQuestionSelect(id)
      return
    }

    if (event) {
      event.stopPropagation()
    }

    const newSelected = new Set(selectedIds)

    if (newSelected.has(id)) {
      newSelected.delete(id)
    } else {
      newSelected.add(id)
    }

    setSelectedIds(newSelected)
    if (onQuestionsSelected) {
      onQuestionsSelected(Array.from(newSelected))
    }
  }

  const selectAll = () => {
    const allIds = new Set(questions.map(q => q.id))
    setSelectedIds(allIds)
    if (onQuestionsSelected) {
      onQuestionsSelected(Array.from(allIds))
    }
  }

  const clearSelection = () => {
    setSelectedIds(new Set())
    if (onQuestionsSelected) {
      onQuestionsSelected([])
    }
  }

  const selectFiltered = () => {
    const filteredIds = new Set(filteredQuestions.map(q => q.id))
    setSelectedIds(filteredIds)
    if (onQuestionsSelected) {
      onQuestionsSelected(Array.from(filteredIds))
    }
  }

  // Edit and delete handlers
  const handleEdit = (question, event) => {
    if (event) {
      event.stopPropagation()
    }
    setEditingQuestion(question)
  }

  const handleDelete = async (questionId, event) => {
    if (event) {
      event.stopPropagation()
    }

    // Show confirmation
    setDeletingQuestionId(questionId)
  }

  const confirmDelete = async (questionId) => {
    try {
      const response = await fetch(`http://localhost:8018/api/questions/${questionId}`, {
        method: 'DELETE',
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to delete question')
      }

      // Notify parent component
      if (onQuestionDeleted) {
        onQuestionDeleted(questionId)
      }

      setDeletingQuestionId(null)
    } catch (error) {
      console.error('Delete error:', error)
      alert(`Failed to delete question: ${error.message}`)
      setDeletingQuestionId(null)
    }
  }

  const handleSaveEdit = (updatedQuestion) => {
    // Notify parent component
    if (onQuestionUpdated) {
      onQuestionUpdated(updatedQuestion)
    }
  }

  return (
    <div className="question-list-panel">
      {multiSelectMode && (
        <div className="selection-controls">
          <button onClick={selectAll} className="selection-btn" title="Select all questions">
            Select All
          </button>
          <button onClick={selectFiltered} className="selection-btn" title="Select filtered questions">
            Select Filtered ({filteredQuestions.length})
          </button>
          <button onClick={clearSelection} className="selection-btn" title="Clear selection">
            Clear
          </button>
          <span className="selection-count">
            {selectedIds.size} selected
          </span>
        </div>
      )}


      <div className="question-list-filters">
        <input
          type="text"
          className="search-box"
          placeholder="Search questions..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />

        <div className="filter-row">
          <select
            className="filter-select"
            value={domainFilter}
            onChange={(e) => setDomainFilter(e.target.value)}
          >
            <option value="all">All Domains</option>
            {domains.map(domain => (
              <option key={domain} value={domain}>{domain}</option>
            ))}
          </select>

          <select
            className="filter-select"
            value={difficultyFilter}
            onChange={(e) => setDifficultyFilter(e.target.value)}
          >
            <option value="all">All Difficulties</option>
            <option value="1">1 - Easy</option>
            <option value="2">2</option>
            <option value="3">3 - Medium</option>
            <option value="4">4</option>
            <option value="5">5 - Hard</option>
          </select>
        </div>

        <div className="filter-row">
          <select
            className="filter-select"
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
          >
            <option value="all">All Sources</option>
            {sources.map(source => (
              <option key={source} value={source}>{source}</option>
            ))}
          </select>

          {hasActiveFilters && (
            <button className="clear-filters-btn" onClick={handleClearFilters}>
              Clear
            </button>
          )}
        </div>
      </div>

      <div className="question-list-content">
        {filteredQuestions.length === 0 ? (
          <div className="question-list-empty">
            <div className="question-list-empty-icon">📋</div>
            <div>No questions found</div>
            {hasActiveFilters && <div style={{ fontSize: '12px', marginTop: '8px' }}>Try adjusting your filters</div>}
          </div>
        ) : (
          filteredQuestions.map(q => (
            <div
              key={q.id}
              className={`question-list-item ${selectedQuestionId === q.id ? 'selected' : ''
                } ${selectedIds.has(q.id) ? 'multi-selected' : ''}`}
              onClick={(e) => toggleSelection(q.id, e)}
            >
              {multiSelectMode && (
                <input
                  type="checkbox"
                  checked={selectedIds.has(q.id)}
                  onChange={(e) => toggleSelection(q.id, e)}
                  onClick={(e) => e.stopPropagation()}
                  className="question-checkbox"
                />
              )}
              <div className="question-item-content">
                <div className="question-item-header">
                  <div className="question-item-badges">
                    <span className="badge domain">{q.domain}</span>
                    <span className={`badge difficulty difficulty-${q.difficulty}`}>
                      Lvl {q.difficulty}
                    </span>
                  </div>
                  <div className="question-item-actions">
                    <button
                      className="action-btn edit-btn"
                      onClick={(e) => handleEdit(q, e)}
                      title="Edit question"
                    >
                      ✏️
                    </button>
                    <button
                      className="action-btn delete-btn"
                      onClick={(e) => handleDelete(q.id, e)}
                      title="Delete question"
                    >
                      🗑️
                    </button>
                  </div>
                </div>
                <div className="question-item-text">{q.question_text}</div>
                <div className="question-item-meta">
                  <div className="meta-item">
                    <span className="meta-label">Type:</span>
                    <span>{q.question_type}</span>
                  </div>
                  {q.source && (
                    <div className="meta-item">
                      <span className="meta-label">Source:</span>
                      <span>{q.source}</span>
                    </div>
                  )}
                  {q.target_event_id && (
                    <div className="meta-item">
                      <span className="meta-label">📍</span>
                      <span>Has target event</span>
                    </div>
                  )}
                  {q.related_event_ids && q.related_event_ids.length > 0 && (
                    <div className="meta-item">
                      <span className="meta-label">🔗</span>
                      <span>{q.related_event_ids.length} related</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {filteredQuestions.length > 0 && (
        <div className="question-list-stats">
          Showing {filteredQuestions.length} of {questions.length} questions
        </div>
      )}

      {/* Edit modal */}
      {editingQuestion && (
        <QuestionEditModal
          question={editingQuestion}
          onClose={() => setEditingQuestion(null)}
          onSave={handleSaveEdit}
        />
      )}

      {/* Delete confirmation dialog */}
      {deletingQuestionId && (
        <div className="modal-overlay" onClick={() => setDeletingQuestionId(null)}>
          <div className="confirmation-dialog" onClick={(e) => e.stopPropagation()}>
            <h3>Delete Question?</h3>
            <p>Are you sure you want to delete this question? This action cannot be undone.</p>
            <div className="confirmation-actions">
              <button
                className="btn btn-secondary"
                onClick={() => setDeletingQuestionId(null)}
              >
                Cancel
              </button>
              <button
                className="btn btn-danger"
                onClick={() => confirmDelete(deletingQuestionId)}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
})

export default QuestionList
