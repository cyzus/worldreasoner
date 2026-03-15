import React, { useState, useMemo } from 'react'

const DIRECTION_SIGN = { positive: 1, negative: -1, neutral: 0, mixed: 0 }
const DIRECTION_COLOR = { positive: '#22c55e', negative: '#ef4444', neutral: '#94a3b8', mixed: '#a855f7' }

const fmt = (ts) =>
    new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

function pickRelevantImpact(eventImpacts, groundTruthScenario) {
    if (!eventImpacts || eventImpacts.length === 0) return null
    const actual = eventImpacts.find(i => i.outcomeIsActual)
    if (actual) return actual
    if (groundTruthScenario) {
        const scenario = eventImpacts.find(i => i.outcomeScenario === groundTruthScenario)
        if (scenario) return scenario
    }
    return eventImpacts[0]
}

/**
 * CausalPressureChart
 *
 * Step chart showing cumulative causal pressure over time, with optional
 * Polymarket price history overlaid as a smooth curve on a dual Y axis.
 *
 * Props:
 *   events            - sorted event nodes
 *   impacts           - bySource dict: { [eventId]: ImpactRecord[] }
 *   groundTruthScenario - 'positive_resolution' | 'negative_resolution' | null
 *   resolutionDate    - ISO string (optional)
 *   priceHistory      - { [tokenId]: [{t: unixSec, p: probability}] } or null
 *   priceOutcomes     - token label map or outcomes array (for legend)
 */
export function CausalPressureChart({
    events,
    impacts,
    groundTruthScenario,
    resolutionDate,
    priceHistory = null,
    priceOutcomes = null,
}) {
    const [hoveredIdx, setHoveredIdx] = useState(null)

    // ── Trajectory ──────────────────────────────────────────────────────────
    const trajectory = useMemo(() => {
        const points = []
        for (const event of events) {
            const impact = pickRelevantImpact(impacts[event.id], groundTruthScenario)
            if (!impact) continue
            const dateStr = event.occurred_date || event.predicted_date ||
                event.properties?.occurred_date || event.properties?.predicted_date
            if (!dateStr) continue

            const direction = impact.impact_direction || 'neutral'
            const magnitude = impact.impact_magnitude ?? 0
            const confidence = impact.confidence ?? 1.0
            const contribution = DIRECTION_SIGN[direction] * magnitude * confidence

            points.push({
                date: new Date(dateStr).getTime(),
                dateStr,
                eventId: event.id,
                eventTitle: event.title || event.label || event.name || event.properties?.title || event.id,
                direction,
                magnitude,
                confidence,
                contribution,
            })
        }
        points.sort((a, b) => a.date - b.date)
        let cumulative = 0
        for (const p of points) {
            cumulative += p.contribution
            p.cumulative = cumulative
        }
        return points
    }, [events, impacts, groundTruthScenario])

    // ── Price series: pick token matching the actual outcome node ────────────
    // The actual outcome is the event node with is_actual_outcome = true.
    // Match its title against the token_outcomes labels (case-insensitive).
    const { priceSeries, priceLabel } = useMemo(() => {
        const empty = { priceSeries: null, priceLabel: 'Market Probability' }
        if (!priceHistory) return empty

        const tokenIds = Object.keys(priceHistory)
        if (tokenIds.length === 0) return empty

        // Build tokenId → label map from priceOutcomes
        const labelMap = {}
        if (priceOutcomes && typeof priceOutcomes === 'object' && !Array.isArray(priceOutcomes)) {
            Object.assign(labelMap, priceOutcomes)
        } else if (Array.isArray(priceOutcomes)) {
            tokenIds.forEach((id, i) => { labelMap[id] = priceOutcomes[i] || `Outcome ${i + 1}` })
        }

        // Find the actual outcome node from events
        const actualOutcomeNode = events.find(e =>
            e.is_actual_outcome ||
            e.properties?.is_actual_outcome
        )
        const actualLabel = actualOutcomeNode
            ? (actualOutcomeNode.title || actualOutcomeNode.label ||
               actualOutcomeNode.name || actualOutcomeNode.properties?.title || '')
            : ''

        // Match actual outcome label against token labels (case-insensitive substring)
        let selectedTokenId = null
        if (actualLabel) {
            const needle = actualLabel.toLowerCase()
            selectedTokenId = tokenIds.find(id =>
                (labelMap[id] || '').toLowerCase().includes(needle) ||
                needle.includes((labelMap[id] || '').toLowerCase())
            )
        }

        // Fall back to first token if no match
        if (!selectedTokenId) selectedTokenId = tokenIds[0]

        const raw = priceHistory[selectedTokenId]
        if (!Array.isArray(raw) || raw.length === 0) return empty

        return {
            priceSeries: raw.map(pt => ({ t: pt.t * 1000, p: pt.p })).sort((a, b) => a.t - b.t),
            priceLabel: labelMap[selectedTokenId] || actualLabel || 'Market Probability',
        }
    }, [priceHistory, priceOutcomes, events])

    if (trajectory.length === 0) return null

    // ── Layout ───────────────────────────────────────────────────────────────
    const W = 680, H = 220
    const PL = 48, PR = priceSeries ? 52 : 20, PT = 24, PB = 36
    const iW = W - PL - PR
    const iH = H - PT - PB

    // X domain covers both trajectory and price series
    const trajDates = trajectory.map(p => p.date)
    const resTs = resolutionDate ? new Date(resolutionDate).getTime() : null
    const allTs = [...trajDates, ...(priceSeries ? priceSeries.map(p => p.t) : []), ...(resTs ? [resTs] : [])]
    const minT = Math.min(...allTs)
    const maxT = Math.max(...allTs)

    // Pressure Y axis (left)
    const pressures = trajectory.map(p => p.cumulative)
    const maxAbs = Math.max(Math.abs(Math.min(...pressures)), Math.abs(Math.max(...pressures)), 0.1)

    const xOf = t => PL + ((t - minT) / (maxT - minT || 1)) * iW
    const yPressure = v => PT + iH / 2 - (v / maxAbs) * (iH / 2)
    const zeroY = PT + iH / 2

    // Price Y axis (right): always [0, 1]
    const yPrice = p => PT + iH - p * iH

    // ── Step path (pressure) ─────────────────────────────────────────────────
    let stepD = `M ${xOf(minT)} ${yPressure(0)}`
    let prev = 0
    trajectory.forEach(p => {
        const x = xOf(p.date)
        stepD += ` L ${x} ${yPressure(prev)} L ${x} ${yPressure(p.cumulative)}`
        prev = p.cumulative
    })
    stepD += ` L ${xOf(maxT)} ${yPressure(prev)}`
    const areaD = `${stepD} L ${xOf(maxT)} ${zeroY} L ${xOf(minT)} ${zeroY} Z`

    const net = trajectory[trajectory.length - 1].cumulative
    const netColor = net > 0.05 ? '#22c55e' : net < -0.05 ? '#ef4444' : '#94a3b8'

    // ── Price polyline ────────────────────────────────────────────────────────
    const pricePolyline = priceSeries
        ? priceSeries.map(pt => `${xOf(pt.t)},${yPrice(pt.p)}`).join(' ')
        : null

    const yTicks = [-maxAbs, -maxAbs / 2, 0, maxAbs / 2, maxAbs]
    const pTicks = [0, 0.25, 0.5, 0.75, 1.0]

    return (
        <div style={{ marginBottom: '8px' }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '6px' }}>
                <div>
                    <span style={{ fontSize: '0.85rem', fontWeight: '600', color: '#333' }}>
                        Causal Pressure Toward Outcome
                    </span>
                    {priceSeries && (
                        <span style={{ fontSize: '0.75rem', color: '#6c757d', marginLeft: '8px' }}>
                            overlaid with market price
                        </span>
                    )}
                </div>
                <span style={{
                    fontSize: '0.8rem', fontWeight: '700', color: netColor,
                    padding: '2px 8px', backgroundColor: netColor + '18', borderRadius: '4px'
                }}>
                    Net {net > 0 ? '+' : ''}{net.toFixed(3)}
                </span>
            </div>

            <svg width={W} height={H} style={{ display: 'block', overflow: 'visible', maxWidth: '100%' }}>

                {/* ── Left Y axis: pressure ── */}
                {yTicks.map((v, i) => (
                    <g key={i}>
                        <line
                            x1={PL} y1={yPressure(v)} x2={W - PR} y2={yPressure(v)}
                            stroke={v === 0 ? '#adb5bd' : '#e9ecef'}
                            strokeWidth={v === 0 ? 1.2 : 0.7}
                            strokeDasharray={v === 0 ? 'none' : '4,3'}
                        />
                        <text x={PL - 5} y={yPressure(v) + 3.5} textAnchor="end" fontSize={9} fill="#64748b">
                            {v === 0 ? '0' : (v > 0 ? '+' : '') + v.toFixed(2)}
                        </text>
                    </g>
                ))}
                <text
                    transform={`rotate(-90) translate(${-(PT + iH / 2)}, ${PL - 36})`}
                    textAnchor="middle" fontSize={9} fill="#64748b"
                >
                    causal pressure
                </text>

                {/* ── Right Y axis: price ── */}
                {priceSeries && pTicks.map((v, i) => (
                    <g key={i}>
                        <text x={W - PR + 5} y={yPrice(v) + 3.5} textAnchor="start" fontSize={9} fill="#3b82f6">
                            {(v * 100).toFixed(0)}%
                        </text>
                        {v === 0.5 && (
                            <line
                                x1={PL} y1={yPrice(0.5)} x2={W - PR} y2={yPrice(0.5)}
                                stroke="#3b82f6" strokeWidth={0.5} strokeDasharray="3,4" strokeOpacity={0.4}
                            />
                        )}
                    </g>
                ))}
                {priceSeries && (
                    <text
                        transform={`rotate(90) translate(${PT + iH / 2}, ${-(W - PR + 40)})`}
                        textAnchor="middle" fontSize={9} fill="#3b82f6"
                    >
                        {priceLabel}
                    </text>
                )}

                {/* ── Pressure area + step line ── */}
                <path d={areaD} fill={net >= 0 ? '#22c55e' : '#ef4444'} fillOpacity={0.07} />
                <path d={stepD} fill="none" stroke={netColor} strokeWidth={2} />

                {/* ── Price polyline ── */}
                {pricePolyline && (
                    <polyline
                        points={pricePolyline}
                        fill="none"
                        stroke="#3b82f6"
                        strokeWidth={1.5}
                        strokeOpacity={0.75}
                    />
                )}

                {/* ── Resolution date ── */}
                {resTs && (
                    <g>
                        <line
                            x1={xOf(resTs)} y1={PT} x2={xOf(resTs)} y2={PT + iH}
                            stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="5,3"
                        />
                        <text x={xOf(resTs) + 4} y={PT + 10} fontSize={9} fill="#f59e0b" fontWeight="600">
                            resolved
                        </text>
                    </g>
                )}

                {/* ── Event dots ── */}
                {trajectory.map((p, i) => {
                    const cx = xOf(p.date)
                    const cy = yPressure(p.cumulative)
                    const color = DIRECTION_COLOR[p.direction] || '#94a3b8'
                    const isHovered = hoveredIdx === i

                    return (
                        <g key={i}>
                            <circle
                                cx={cx} cy={cy}
                                r={isHovered ? 6 : 4}
                                fill={color} stroke="#fff" strokeWidth={1.5}
                                style={{ cursor: 'pointer', transition: 'r 0.1s' }}
                                onMouseEnter={() => setHoveredIdx(i)}
                                onMouseLeave={() => setHoveredIdx(null)}
                            />

                            {isHovered && (() => {
                                // Find nearest price at this event's date
                                let nearestPrice = null
                                if (priceSeries) {
                                    const closest = priceSeries.reduce((best, pt) =>
                                        Math.abs(pt.t - p.date) < Math.abs(best.t - p.date) ? pt : best
                                    )
                                    nearestPrice = closest.p
                                }

                                const tipW = 190, tipH = nearestPrice !== null ? 70 : 58
                                const flipX = cx + tipW + 10 > W - PR
                                const tx = flipX ? cx - tipW - 6 : cx + 8
                                const ty = Math.max(PT, Math.min(cy - tipH / 2, PT + iH - tipH))

                                return (
                                    <g style={{ pointerEvents: 'none' }}>
                                        <rect x={tx} y={ty} width={tipW} height={tipH} rx={4}
                                            fill="#1e293b" fillOpacity={0.93} />
                                        <text x={tx + 8} y={ty + 14} fontSize={9.5} fill="#fff" fontWeight="600">
                                            {p.eventTitle.length > 27 ? p.eventTitle.substring(0, 27) + '…' : p.eventTitle}
                                        </text>
                                        <text x={tx + 8} y={ty + 26} fontSize={8.5} fill="#94a3b8">
                                            {fmt(p.date)}
                                        </text>
                                        <text x={tx + 8} y={ty + 39} fontSize={8.5} fill={color} fontWeight="600">
                                            {p.direction}
                                        </text>
                                        <text x={tx + 8} y={ty + 50} fontSize={8} fill="#cbd5e1">
                                            mag {(p.magnitude * 100).toFixed(0)}% · conf {(p.confidence * 100).toFixed(0)}% · Δ{p.contribution > 0 ? '+' : ''}{p.contribution.toFixed(3)}
                                        </text>
                                        {nearestPrice !== null && (
                                            <text x={tx + 8} y={ty + 62} fontSize={8} fill="#93c5fd">
                                                market price at event: {(nearestPrice * 100).toFixed(1)}%
                                            </text>
                                        )}
                                    </g>
                                )
                            })()}
                        </g>
                    )
                })}

                {/* ── X axis date labels ── */}
                <text x={xOf(minT)} y={PT + iH + 14} fontSize={9} fill="#adb5bd" textAnchor="middle">
                    {fmt(minT)}
                </text>
                <text x={xOf(maxT)} y={PT + iH + 14} fontSize={9} fill="#adb5bd" textAnchor="middle">
                    {fmt(maxT)}
                </text>
            </svg>

            {/* Legend */}
            <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', marginTop: '4px' }}>
                {Object.entries(DIRECTION_COLOR).map(([dir, color]) => (
                    <span key={dir} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.72rem', color: '#6c757d' }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: color, display: 'inline-block' }} />
                        {dir}
                    </span>
                ))}
                {priceSeries && (
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.72rem', color: '#6c757d' }}>
                        <span style={{ width: 18, height: 2, backgroundColor: '#3b82f6', display: 'inline-block', borderRadius: 1 }} />
                        {priceLabel}
                    </span>
                )}
            </div>
        </div>
    )
}
