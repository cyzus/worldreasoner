import React, { useState } from 'react'
import { useEventImpacts, useOutcomeImpacts } from '../../hooks/queries/useEventQueries'

const getDirectionInfo = (direction) => {
    switch (direction) {
        case 'positive': return { icon: '↗', color: '#22c55e', label: 'Positive' }
        case 'negative': return { icon: '↘', color: '#ef4444', label: 'Negative' }
        case 'mixed': return { icon: '↔', color: '#a855f7', label: 'Mixed' }
        case 'neutral': return { icon: '→', color: '#94a3b8', label: 'Neutral' }
        default: return { icon: '?', color: '#6c757d', label: 'Unknown' }
    }
}

export const EventImpacts = ({ node, show, onToggle }) => {
    const [minConfidence, setMinConfidence] = useState(0)
    const [filterDirection, setFilterDirection] = useState(null)

    // Get impacts based on node type
    const isOutcome = !!node.isOutcome
    const regularQuery = useEventImpacts(node.id, show && !isOutcome)
    const outcomeQuery = useOutcomeImpacts(node.id, minConfidence, filterDirection, show && isOutcome)

    const query = isOutcome ? outcomeQuery : regularQuery
    const { data, isLoading, isFetched } = query
    const impacts = data || []

    return (
        <div className="expandable-section">
            <button
                className={`section-toggle ${show ? 'active' : ''}`}
                onClick={onToggle}
                style={{ padding: '8px 12px', fontSize: '0.9rem' }}
            >
                <span className="toggle-text">
                    {isOutcome ? '⭐ Impacted By' : '🎯 Impact on Outcome'}
                </span>
                <span className="toggle-meta" style={{ fontSize: '0.8rem' }}>
                    {isFetched ? impacts.length : ''}
                    <span className="toggle-icon">{show ? '−' : '+'}</span>
                </span>
            </button>

            {/* Filters for outcome events */}
            {show && isOutcome && (
                <div style={{
                    padding: '8px 12px',
                    backgroundColor: '#f8f9fa',
                    borderTop: '1px solid #e9ecef',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px'
                }}>
                    <div>
                        <label style={{ fontSize: '0.75rem', color: '#666', display: 'block', marginBottom: '4px' }}>
                            Min Confidence: {(minConfidence * 100).toFixed(0)}%
                        </label>
                        <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.1"
                            value={minConfidence}
                            onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
                            style={{ width: '100%' }}
                        />
                    </div>
                    <div>
                        <label style={{ fontSize: '0.75rem', color: '#666', display: 'block', marginBottom: '4px' }}>
                            Direction
                        </label>
                        <select
                            value={filterDirection || ''}
                            onChange={(e) => setFilterDirection(e.target.value || null)}
                            style={{
                                width: '100%',
                                padding: '4px 8px',
                                fontSize: '0.8rem',
                                borderRadius: '4px',
                                border: '1px solid #ced4da'
                            }}
                        >
                            <option value="">All</option>
                            <option value="positive">Positive</option>
                            <option value="negative">Negative</option>
                            <option value="mixed">Mixed</option>
                            <option value="neutral">Neutral</option>
                        </select>
                    </div>
                </div>
            )}

            {show && (
                <div className="section-content">
                    {isLoading ? (
                        <div className="loading-message">Loading...</div>
                    ) : impacts.length === 0 ? (
                        <div className="empty-message">No impacts</div>
                    ) : (
                        <div className="impacts-list">
                            {impacts.map((impact, index) => {
                                const dirInfo = getDirectionInfo(impact.properties?.impact_direction)
                                const magnitude = impact.properties?.impact_magnitude || 0
                                const confidence = impact.properties?.confidence || 0
                                const reasoning = impact.properties?.reasoning || 'No reasoning'
                                const evidenceCount = impact.properties?.evidence_count || 0
                                const chainCount = impact.properties?.causal_chain_hypothesis_ids?.length || 0

                                const eventId = isOutcome ? impact.source_id : impact.target_id
                                const eventLabel = impact.label || `Event ${eventId?.substring(0, 8)}`

                                return (
                                    <div key={index} className="impact-item" style={{
                                        padding: '10px',
                                        marginBottom: '8px',
                                        border: '1px solid #e0e0e0',
                                        borderRadius: '6px',
                                        backgroundColor: '#fff'
                                    }}>
                                        {eventId && (
                                            <div style={{
                                                fontSize: '0.8rem',
                                                fontWeight: '600',
                                                color: '#495057',
                                                marginBottom: '6px',
                                                paddingBottom: '6px',
                                                borderBottom: '1px solid #f0f0f0'
                                            }}>
                                                {isOutcome ? '← From: ' : '→ To: '}{eventLabel}
                                            </div>
                                        )}
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
                                            borderRadius: '4px',
                                            marginBottom: '6px'
                                        }}>
                                            {reasoning}
                                        </div>
                                        {(evidenceCount > 0 || chainCount > 0) && (
                                            <div style={{
                                                display: 'flex',
                                                gap: '10px',
                                                fontSize: '0.7rem',
                                                color: '#6c757d'
                                            }}>
                                                {evidenceCount > 0 && (
                                                    <span>📄 {evidenceCount} evidence article{evidenceCount !== 1 ? 's' : ''}</span>
                                                )}
                                                {chainCount > 0 && (
                                                    <span>🔗 {chainCount} causal link{chainCount !== 1 ? 's' : ''}</span>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
