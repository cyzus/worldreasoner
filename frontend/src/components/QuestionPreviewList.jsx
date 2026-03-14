import React, { useState, useMemo } from 'react'
import QuestionCard from './QuestionCard'
import { useQuestions } from '../hooks/useQueries'
import './QuestionPreviewList.css'

/**
 * QuestionPreviewList - Display and select questions for saving
 */
function QuestionPreviewList({ questions, onSaveSelected, loading, source }) {
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [searchText, setSearchText] = useState('')
  const [domainFilter, setDomainFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [sortBy, setSortBy] = useState('default')

  const { data: dbQuestions } = useQuestions()
  const dbIds = useMemo(() => {
    const list = Array.isArray(dbQuestions) ? dbQuestions : (dbQuestions?.questions ?? [])
    return new Set(list.map(q => q.id))
  }, [dbQuestions])

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
    if (sortBy !== 'default') {
      filtered = [...filtered].sort((a, b) => {
        switch (sortBy) {
          case 'difficulty':
            return (b.difficulty || 0) - (a.difficulty || 0)
          case 'date':
            if (!a.resolution_date) return 1
            if (!b.resolution_date) return -1
            return new Date(b.resolution_date) - new Date(a.resolution_date)
          case 'quality':
            return (b.quality_score || 0) - (a.quality_score || 0)
          case 'volume':
            const volA = a.metadata?.volume_usd || a.metadata?.volume || 0;
            const volB = b.metadata?.volume_usd || b.metadata?.volume || 0;
            return volB - volA;
          default:
            return 0;
        }
      })
    }

    return filtered
  }, [questions, searchText, domainFilter, typeFilter, sortBy])

  const handleToggleSelect = (questionId) => {
    if (dbIds.has(questionId)) return
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
    setSelectedIds(new Set(filteredQuestions.filter(q => !dbIds.has(q.id)).map(q => q.id)))
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
          📋 Preview ({filteredQuestions.length} of {safeQuestions.length}
          {dbIds.size > 0 && filteredQuestions.some(q => dbIds.has(q.id)) && (
            <span style={{ fontSize: '0.8em', color: '#888', fontWeight: 'normal', marginLeft: '6px' }}>
              · {filteredQuestions.filter(q => dbIds.has(q.id)).length} already saved
            </span>
          )})
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
                <option value="default">Default / Trending</option>
                <option value="volume">Sort by Volume</option>
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
              <QuestionCard
                key={question.id}
                question={question}
                isSelected={selectedIds.has(question.id)}
                isMultiSelected={selectedIds.has(question.id)}
                onToggleSelect={() => handleToggleSelect(question.id)}
                showCheckbox={true}
                showSelectionStyle={true}
                isInDb={dbIds.has(question.id)}
                actions={
                  source === 'polymarket' && question.metadata?.market_slug && (
                    <a
                      href={`https://polymarket.com/event/${question.metadata.market_slug}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => e.stopPropagation()}
                      className="link-badge"
                    >
                      View Link ↗
                    </a>
                  )
                }
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export default QuestionPreviewList
