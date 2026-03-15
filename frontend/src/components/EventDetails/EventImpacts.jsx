import React, { useState } from 'react'
import { useEventImpacts, useOutcomeImpacts, useOutcomeTrajectory } from '../../hooks/queries/useEventQueries'

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
    const [hoveredPoint, setHoveredPoint] = useState(null)

    // Get impacts based on node type
    const isOutcome = !!node.isOutcome
    const regularQuery = useEventImpacts(node.id, show && !isOutcome)
    const outcomeQuery = useOutcomeImpacts(node.id, minConfidence, filterDirection, show && isOutcome)
    const trajectoryQuery = useOutcomeTrajectory(node.id, show && isOutcome)

    const query = isOutcome ? outcomeQuery : regularQuery
    const { data, isLoading, isFetched } = query
    const impacts = data || []
    const trajectory = trajectoryQuery.data || null

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

            {/* Trajectory chart — only for outcome nodes with data */}
            {show && isOutcome && trajectory && trajectory.trajectory.length > 0 && (() => {
                const points = trajectory.trajectory
                const W = 280, H = 100, PX = 32, PY = 12
                const iW = W - PX * 2, iH = H - PY * 2

                const dates = points.map(p => new Date(p.date).getTime())
                const minT = Math.min(...dates), maxT = Math.max(...dates)
                const pressures = points.map(p => p.cumulative_pressure)
                const maxAbs = Math.max(Math.abs(Math.min(...pressures)), Math.abs(Math.max(...pressures)), 0.01)

                const xOf = t => PX + ((t - minT) / (maxT - minT || 1)) * iW
                const yOf = v => PY + iH / 2 - (v / maxAbs) * (iH / 2)
                const zeroY = PY + iH / 2

                let pathD = `M ${xOf(dates[0])} ${yOf(0)}`
                let prev = 0
                points.forEach((p, i) => {
                    const x = xOf(dates[i])
                    pathD += ` L ${x} ${yOf(prev)} L ${x} ${yOf(p.cumulative_pressure)}`
                    prev = p.cumulative_pressure
                })
                pathD += ` L ${xOf(maxT)} ${yOf(prev)}`
                const areaD = pathD + ` L ${xOf(maxT)} ${zeroY} L ${xOf(dates[0])} ${zeroY} Z`

                const net = trajectory.summary.net_pressure
                const netColor = net > 0 ? '#22c55e' : net < 0 ? '#ef4444' : '#94a3b8'

                return (
                    <div style={{ padding: '10px 12px', borderTop: '1px solid #f0f0f0', backgroundColor: '#fafafa' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                            <span style={{ fontSize: '0.72rem', fontWeight: '600', color: '#495057' }}>Causal Pressure Over Time</span>
                            <span style={{ fontSize: '0.72rem', color: netColor, fontWeight: '600' }}>
                                Net {net > 0 ? '+' : ''}{net.toFixed(2)}
                            </span>
                        </div>
                        <svg width={W} height={H} style={{ display: 'block', overflow: 'visible' }}>
                            <line x1={PX} y1={zeroY} x2={W - PX} y2={zeroY} stroke="#dee2e6" strokeWidth={1} />
                            <line x1={PX} y1={PY} x2={W - PX} y2={PY} stroke="#dee2e6" strokeWidth={0.5} strokeDasharray="3,2" />
                            <line x1={PX} y1={H - PY} x2={W - PX} y2={H - PY} stroke="#dee2e6" strokeWidth={0.5} strokeDasharray="3,2" />
                            <text x={PX - 3} y={PY + 3} textAnchor="end" fontSize={7} fill="#adb5bd">+{maxAbs.toFixed(1)}</text>
                            <text x={PX - 3} y={H - PY + 3} textAnchor="end" fontSize={7} fill="#adb5bd">-{maxAbs.toFixed(1)}</text>
                            <text x={PX - 3} y={zeroY + 3} textAnchor="end" fontSize={7} fill="#adb5bd">0</text>
                            <path d={areaD} fill={net >= 0 ? '#22c55e' : '#ef4444'} fillOpacity={0.08} />
                            <path d={pathD} fill="none" stroke={net >= 0 ? '#22c55e' : '#ef4444'} strokeWidth={1.5} />
                            {points.map((p, i) => {
                                const cx = xOf(dates[i])
                                const cy = yOf(p.cumulative_pressure)
                                const dotColor = p.direction === 'positive' ? '#22c55e' : p.direction === 'negative' ? '#ef4444' : '#94a3b8'
                                return (
                                    <g key={i}>
                                        <circle
                                            cx={cx} cy={cy} r={hoveredPoint === i ? 5 : 3.5}
                                            fill={dotColor} stroke="#fff" strokeWidth={1.2}
                                            style={{ cursor: 'pointer' }}
                                            onMouseEnter={() => setHoveredPoint(i)}
                                            onMouseLeave={() => setHoveredPoint(null)}
                                        />
                                        {hoveredPoint === i && (
                                            <g>
                                                <rect
                                                    x={Math.min(cx + 6, W - PX - 95)} y={cy - 26}
                                                    width={94} height={24} rx={3}
                                                    fill="#333" fillOpacity={0.88}
                                                />
                                                <text x={Math.min(cx + 9, W - PX - 92)} y={cy - 15} fontSize={7.5} fill="#fff">
                                                    {p.event_title.substring(0, 24)}{p.event_title.length > 24 ? '…' : ''}
                                                </text>
                                                <text x={Math.min(cx + 9, W - PX - 92)} y={cy - 6} fontSize={7} fill="#ccc">
                                                    {p.direction} · {(p.magnitude * 100).toFixed(0)}% · {(p.confidence * 100).toFixed(0)}% conf
                                                </text>
                                            </g>
                                        )}
                                    </g>
                                )
                            })}
                        </svg>
                    </div>
                )
            })()}

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
