import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { reviewEvent, reviewQuestionEvents } from '../../api/graphApi'

const formatDate = (dateString) => {
    if (!dateString) return 'Unknown Date'
    return new Date(dateString).toLocaleDateString(undefined, {
        month: 'short', day: 'numeric', year: 'numeric'
    })
}

const getOutcomeAlignedImpacts = (impacts, groundTruthScenario) => {
    if (!impacts || impacts.length === 0) return []

    // Prefer impacts tied to the explicit actual outcome when present.
    const actualOutcomeImpacts = impacts.filter(imp => imp.outcomeIsActual)
    if (actualOutcomeImpacts.length > 0) return actualOutcomeImpacts

    // Fallback: align to the scenario resolved by ground truth.
    if (groundTruthScenario) {
        const truthAligned = impacts.filter(imp => imp.outcomeScenario === groundTruthScenario)
        if (truthAligned.length > 0) return truthAligned
    }

    return impacts
}

const computeNetDirection = (impacts) => {
    if (!impacts || impacts.length === 0) return null

    const directions = impacts
        .map(imp => imp.impact_direction)
        .filter(dir => dir && dir !== 'neutral')

    if (directions.length === 0) return null
    if (directions.every(d => d === 'positive')) return 'positive'
    if (directions.every(d => d === 'negative')) return 'negative'
    return 'mixed'
}

export function CausalEventsTable({
    events,
    impacts,
    articleMap,
    groundTruthScenario,
    questionId,
    showHeader = true
}) {
    const [expandedRows, setExpandedRows] = useState(new Set())
    const [localReviewStatus, setLocalReviewStatus] = useState({})
    const [localReviewNotes, setLocalReviewNotes] = useState({})
    const [isReviewingAll, setIsReviewingAll] = useState(false)

    const toggleRow = (id) => {
        const newExpanded = new Set(expandedRows)
        if (newExpanded.has(id)) newExpanded.delete(id)
        else newExpanded.add(id)
        setExpandedRows(newExpanded)
    }

    const handleReviewAll = async () => {
        if (!questionId) return
        setIsReviewingAll(true)
        try {
            const result = await reviewQuestionEvents(questionId)
            alert(`Review complete: ${result.approved_events} approved, ${result.rejected_events} rejected.`)

            // Update local state for all reviewed events
            const newStatuses = { ...localReviewStatus }
            const newNotes = { ...localReviewNotes }
            result.event_reviews.forEach(r => {
                newStatuses[r.event_id] = r.approved ? 'approved' : 'rejected'
                newNotes[r.event_id] = `LLM Review: ${r.reasoning}`
            })
            setLocalReviewStatus(newStatuses)
            setLocalReviewNotes(newNotes)
        } catch (error) {
            console.error('Error auto-reviewing events:', error)
            alert('Failed to auto-review events.')
        } finally {
            setIsReviewingAll(false)
        }
    }

    return (
        <div className="cs-section">
            <div className="cs-section-header-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                {showHeader && (
                    <div>
                        <h3 className="cs-section-title">Causal Events</h3>
                        <p className="cs-section-subtitle">Chronological progression of key events extracted from the evidence</p>
                    </div>
                )}
                {questionId && events.length > 0 && (
                    <button
                        className="cs-btn-review-all"
                        onClick={handleReviewAll}
                        disabled={isReviewingAll}
                        style={{ padding: '6px 12px', fontSize: '0.85rem', cursor: 'pointer', borderRadius: '4px', border: '1px solid #dee2e6', backgroundColor: '#fff' }}
                    >
                        {isReviewingAll ? '⏳ Reviewing...' : '🤖 Auto-Review Pending'}
                    </button>
                )}
            </div>

            {events.length === 0 ? (
                <div className="cs-empty">No events found in the current graph.</div>
            ) : (
                <div className="cs-table-container">
                    <table className="cs-table">
                        <thead>
                            <tr>
                                <th>Date</th>
                                <th>Event Summary</th>
                                <th>Impact</th>
                                <th>Review</th>
                            </tr>
                        </thead>
                        <tbody>
                            {events.map(event => {
                                const isOutcome = event.isOutcome || event.properties?.is_outcome || event.properties?.is_actual_outcome
                                const isGroundTruth = isOutcome && (
                                    event.properties?.is_actual_outcome === true ||
                                    (groundTruthScenario && event.properties?.outcome_scenario === groundTruthScenario)
                                )
                                const dateStr = event.occurred_date || event.predicted_date || event.properties?.occurred_date || event.properties?.predicted_date
                                const title = event.title || event.name || event.properties?.title || 'Unnamed Event'
                                const titleStr = title.length > 100 ? title.substring(0, 100) + '...' : title

                                const outcomeImpacts = impacts[event.id] || []
                                const alignedImpacts = getOutcomeAlignedImpacts(
                                    outcomeImpacts,
                                    groundTruthScenario
                                )
                                const impactDirection = computeNetDirection(alignedImpacts) ||
                                    event.impact_direction ||
                                    event.properties?.impact_direction


                                const actualReviewStatus = localReviewStatus[event.id] || event.review_status || event.properties?.review_status || 'pending'
                                const actualReviewNote = localReviewNotes[event.id] || event.review_note || event.properties?.review_note
                                const isExpanded = expandedRows.has(event.id)

                                return (
                                    <React.Fragment key={event.id}>
                                        <tr
                                            className={`${isOutcome ? 'cs-row-outcome' : ''} ${isExpanded ? 'cs-row-expanded' : ''}`}
                                            onClick={() => toggleRow(event.id)}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            <td className="cs-td-date">{formatDate(dateStr)}</td>
                                            <td className="cs-td-main">
                                                <div className="cs-event-title">
                                                    {isOutcome && <span className="cs-badge-outcome">OUTCOME</span>}
                                                    {isGroundTruth && <span className="cs-badge-ground-truth">✓ Ground Truth</span>}
                                                    {titleStr}
                                                    <span className={`cs-expand-icon ${isExpanded ? 'open' : ''}`}>▼</span>
                                                </div>
                                            </td>
                                            <td className="cs-td-impact">
                                                {!isOutcome && impactDirection && (
                                                    <span className={`cs-impact-badge cs-impact-${impactDirection}`}>
                                                        {impactDirection}
                                                    </span>
                                                )}
                                            </td>
                                            <td className="cs-td-review">
                                                <div className="cs-review-cell" style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignItems: 'flex-start' }}>
                                                    <span className={`cs-badge-review cs-review-${actualReviewStatus.toLowerCase()}`}>
                                                        {actualReviewStatus.toUpperCase()}
                                                    </span>
                                                </div>
                                            </td>
                                        </tr>
                                        {isExpanded && (
                                            <tr className="cs-row-details">
                                                <td colSpan="3">
                                                    <div className="cs-details-content">
                                                        <div className="cs-details-header">
                                                            <p><strong>Description:</strong> {event.description || event.properties?.description || 'No description available.'}</p>

                                                            {actualReviewNote && (
                                                                <div className="cs-review-note" style={{ marginTop: '8px', padding: '10px 12px', backgroundColor: '#f8f9fa', borderLeft: '3px solid #868e96', fontSize: '0.9rem', borderRadius: '0 4px 4px 0' }}>
                                                                    <strong>🤖 Review Reason:</strong>
                                                                    <div style={{ marginTop: '4px', whiteSpace: 'pre-wrap', color: '#495057' }}>{actualReviewNote}</div>
                                                                </div>
                                                            )}

                                                            <div className="cs-evidence-section">
                                                                <span className="cs-evidence-label">Source Evidence:</span>
                                                                <div className="cs-evidence-links">
                                                                    {Array.from(new Set([
                                                                        ...(event.article_ids || []),
                                                                        ...(event.properties?.article_ids || []),
                                                                        event.source_article_id,
                                                                        event.properties?.source_article_id
                                                                    ])).filter(Boolean).map(id => {
                                                                        const art = articleMap[id]
                                                                        return (
                                                                            <a
                                                                                key={id}
                                                                                href={art?.url || `#art-${id}`}
                                                                                target={art?.url ? "_blank" : "_self"}
                                                                                rel={art?.url ? "noopener noreferrer" : ""}
                                                                                className="cs-evidence-pill"
                                                                                title={art?.title}
                                                                            >
                                                                                {art ? `${art.source || 'Source'}: ${art.title.substring(0, 30)}...` : `Doc ${id.substring(0, 6)}`}
                                                                            </a>
                                                                        )
                                                                    })}
                                                                    {(!event.article_ids?.length && !event.properties?.article_ids?.length && !event.source_article_id) &&
                                                                        <span className="cs-no-evidence">No direct sources linked.</span>
                                                                    }
                                                                </div>
                                                            </div>
                                                        </div>

                                                        {outcomeImpacts.length > 0 && (
                                                            <div className="cs-impact-details">
                                                                <h4>Impact Analysis</h4>
                                                                {outcomeImpacts.map((imp, idx) => (
                                                                    <div key={idx} className="cs-impact-item">
                                                                        <div className="cs-impact-meta">
                                                                            <span className="cs-impact-on">Affects <strong>{imp.outcomeTitle}</strong></span>
                                                                            <span className={`cs-impact-badge cs-impact-${imp.impact_direction}`}>
                                                                                {imp.impact_direction} ({Math.round(imp.impact_magnitude * 100)}%)
                                                                            </span>
                                                                            <span className="cs-impact-confidence">
                                                                                Confidence: {Math.round(imp.confidence * 100)}%
                                                                            </span>
                                                                        </div>
                                                                        <div className="cs-impact-reasoning markdown-body">
                                                                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{imp.reasoning}</ReactMarkdown>
                                                                        </div>

                                                                        {imp.articleIds?.length > 0 && (
                                                                            <div className="cs-impact-evidence">
                                                                                <span className="cs-evidence-label">Evidence for this impact:</span>
                                                                                <div className="cs-evidence-links">
                                                                                    {imp.articleIds.map(id => {
                                                                                        const art = articleMap[id]
                                                                                        return (
                                                                                            <a
                                                                                                key={id}
                                                                                                href={art?.url || `#art-${id}`}
                                                                                                target={art?.url ? "_blank" : "_self"}
                                                                                                rel={art?.url ? "noopener noreferrer" : ""}
                                                                                                className="cs-evidence-pill cs-pill-sm"
                                                                                            >
                                                                                                {art ? art.title.substring(0, 40) + '...' : `Evidence ${id.substring(0, 6)}`}
                                                                                            </a>
                                                                                        )
                                                                                    })}
                                                                                </div>
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        )}
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}
