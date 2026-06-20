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
    showSelectionStyle = true,
    isCollecting = false,
    isInDb = false
}) => {
    const q = question

    const handleCardClick = (e) => {
        if (isInDb) return
        if (onClick) {
            onClick(e)
        } else if (onToggleSelect) {
            onToggleSelect(e)
        }
    }

    return (
        <div
            className={`question-list-item ${isSelected && showSelectionStyle && !isInDb ? 'selected' : ''
                } ${isMultiSelected && showSelectionStyle && !isInDb ? 'multi-selected' : ''
                } ${isInDb ? 'in-db' : ''}`}
            onClick={handleCardClick}
        >
            {showCheckbox && (
                <input
                    type="checkbox"
                    checked={isMultiSelected || isSelected}
                    onChange={isInDb ? undefined : onToggleSelect}
                    onClick={(e) => e.stopPropagation()}
                    className="question-checkbox"
                    disabled={isInDb}
                />
            )}

            <div className="question-item-content">
                <div className="question-item-header">
                    <div className="question-item-badges">
                        {isInDb && (
                            <span className="badge in-db-badge">
                                ✓ Already saved
                            </span>
                        )}
                        {isCollecting && (
                            <span className="badge collecting-badge" style={{ backgroundColor: '#e3f2fd', color: '#0d47a1', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <span className="spinner-small" style={{ width: '10px', height: '10px', border: '2px solid #0d47a1', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 1s linear infinite' }}></span>
                                Collecting...
                            </span>
                        )}
                        <span className="badge domain">{q.domain}</span>
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
                        {q.forecast_count > 0 && (
                            <span className="badge forecast-badge" title={`Forecasted ${q.forecast_count} times`}>
                                🎯 {q.forecast_count}
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
                    {q.outcome_event_ids?.length > 0 && (
                        <div className="meta-item">
                            <span className="meta-label">📍</span>
                            <span>{q.outcome_event_ids.length} outcome event{q.outcome_event_ids.length > 1 ? 's' : ''}</span>
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
                {q.ground_truth !== undefined && q.ground_truth !== null && (
                    <div style={{ marginTop: '3px', fontSize: '0.8rem', color: '#166534', backgroundColor: '#dcfce7', padding: '1px 8px', borderRadius: '4px', border: '1px solid #bbf7d0', display: 'inline-block' }}>
                        <strong>✓ Ground Truth:</strong> <span style={{ fontWeight: 600, marginLeft: '4px' }}>
                            {String(q.ground_truth)}
                        </span>
                    </div>
                )}

                {q.resolution_criteria && (
                    <div style={{ marginTop: '4px', fontSize: '0.8rem', color: '#666' }}>
                        <strong>Criteria:</strong> <span style={{ fontStyle: 'italic' }}>{q.resolution_criteria.substring(0, 100)}{q.resolution_criteria.length > 100 ? '...' : ''}</span>
                    </div>
                )}
            </div>
        </div>
    )
})

export default QuestionCard
