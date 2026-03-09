import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'

const formatDate = (dateString) => {
    if (!dateString) return 'Unknown Date'
    return new Date(dateString).toLocaleDateString(undefined, {
        month: 'short', day: 'numeric', year: 'numeric'
    })
}

const computeNetDirection = (impacts) => {
    if (!impacts || impacts.length === 0) return null
    const normalized = impacts
        .map(imp => {
            const dir = imp.impact_direction
            if (!dir || dir === 'neutral') return null
            const scenario = imp.outcomeScenario || ''
            const isNegative = scenario === 'negative_resolution' ||
                (imp.outcomeTitle || '').trim().toLowerCase().startsWith('no ')

            if (isNegative) {
                if (dir === 'positive') return 'negative'
                if (dir === 'negative') return 'positive'
            }
            return dir
        })
        .filter(Boolean)
    if (normalized.length === 0) return null
    if (normalized.every(d => d === 'positive')) return 'positive'
    if (normalized.every(d => d === 'negative')) return 'negative'
    return 'mixed'
}

export function CausalEventsTable({
    events,
    impacts,
    articleMap,
    groundTruthScenario
}) {
    const [expandedRows, setExpandedRows] = useState(new Set())

    const toggleRow = (id) => {
        const newExpanded = new Set(expandedRows)
        if (newExpanded.has(id)) newExpanded.delete(id)
        else newExpanded.add(id)
        setExpandedRows(newExpanded)
    }

    return (
        <div className="cs-section">
            <h3 className="cs-section-title">⚡ Causal Events</h3>
            <p className="cs-section-subtitle">Chronological progression of key events extracted from the evidence</p>

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
                                const impactDirection = computeNetDirection(outcomeImpacts) ||
                                    event.impact_direction ||
                                    event.properties?.impact_direction

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
                                        </tr>
                                        {isExpanded && (
                                            <tr className="cs-row-details">
                                                <td colSpan="3">
                                                    <div className="cs-details-content">
                                                        <div className="cs-details-header">
                                                            <p><strong>Description:</strong> {event.description || event.properties?.description || 'No description available.'}</p>

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
                                                                            <ReactMarkdown>{imp.reasoning}</ReactMarkdown>
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
