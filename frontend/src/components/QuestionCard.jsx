import React, { memo } from 'react'
import './QuestionList.css' // Reuse existings styles for now

/**
 * QuestionCard - Reusable component for displaying a question item
 * 
 * Used by: QuestionList, QuestionPreviewList
 */
const QuestionCard = memo(({
    question,
    isSelected,
    isMultiSelected,
    onToggleSelect,
    onClick,
    actions,
    showCheckbox = false,
    showSelectionStyle = true
}) => {
    const q = question

    const handleCardClick = (e) => {
        if (onClick) {
            onClick(e)
        } else if (onToggleSelect) {
            onToggleSelect(e)
        }
    }

    return (
        <div
            className={`question-list-item ${isSelected && showSelectionStyle ? 'selected' : ''
                } ${isMultiSelected && showSelectionStyle ? 'multi-selected' : ''}`}
            onClick={handleCardClick}
        >
            {showCheckbox && (
                <input
                    type="checkbox"
                    checked={isMultiSelected || isSelected}
                    onChange={onToggleSelect}
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
                        {q.article_count !== undefined && (
                            <span className="badge article-count" title={`${q.article_count} articles collected`}>
                                📄 {q.article_count}
                            </span>
                        )}
                        {q.quality_score > 0 && (
                            <span className="badge" style={{ backgroundColor: '#e9ecef', color: '#495057' }}>
                                Q: {(q.quality_score * 100).toFixed(0)}%
                            </span>
                        )}
                    </div>
                    <div className="question-item-actions">
                        {actions}
                    </div>
                </div>

                <div className="question-item-text">{q.question_text}</div>

                {/* Display options for MCQ */}
                {q.metadata?.options && q.metadata.options.length > 0 && (
                    <div className="question-item-options">
                        <span className="options-label">Options:</span>
                        <div className="options-list">
                            {q.metadata.options.slice(0, 5).map((opt, idx) => (
                                <span key={idx} className="option-badge">
                                    {opt}
                                </span>
                            ))}
                            {q.metadata.options.length > 5 && (
                                <span className="option-badge more">+{q.metadata.options.length - 5}</span>
                            )}
                        </div>
                    </div>
                )}

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
                    {q.resolution_date && (
                        <div className="meta-item">
                            <span className="meta-label">📅</span>
                            <span>{new Date(q.resolution_date).toLocaleDateString()}</span>
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

                {/* Extended details often used in Preview */}
                {q.resolution_criteria && (
                    <div style={{ marginTop: '8px', fontSize: '0.85rem', color: '#666' }}>
                        <strong>Criteria:</strong> <span style={{ fontStyle: 'italic' }}>{q.resolution_criteria.substring(0, 100)}{q.resolution_criteria.length > 100 ? '...' : ''}</span>
                    </div>
                )}
            </div>
        </div>
    )
})

export default QuestionCard
