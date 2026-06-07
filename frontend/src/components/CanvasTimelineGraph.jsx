/**
 * CanvasTimelineGraph — SVG timeline, drag to pan horizontally.
 *
 * Layout rules:
 *  - Axis runs horizontally through the lower third of the canvas.
 *  - All nodes for the same date go into ONE column ABOVE the axis,
 *    stacked top-down with a small gap.  Nothing goes below the axis
 *    except tick labels.
 *  - The total SVG width expands to fit all columns so cards never
 *    clip on the right — the container scrolls horizontally.
 *  - Vertical zoom/pan is provided via buttons; horizontal scroll via
 *    the native scrollbar or trackpad.
 *  - Causal arrows are thin grey horizontal lines along the axis level,
 *    with a small vertical jog to the card bottom.  They never cross cards.
 */
import React, { useMemo, useState, useRef, useEffect, useCallback } from 'react'
import './CanvasTimelineGraph.css'

// ── Layout constants ──────────────────────────────────────────────────────────
const CARD_W    = 130   // card width px
const CARD_H    = 40    // card height px
const CARD_GAP  = 6     // vertical gap between stacked cards
const COL_PAD   = 20    // min horizontal padding between columns
const AXIS_BOT  = 60    // px from bottom of SVG to axis line
const TICK_H    = 5
const LABEL_H   = 16    // height of tick label below axis
const SVG_H     = 400   // fixed SVG height (scrolls horizontally)
const MIN_COL_W = CARD_W + COL_PAD  // min width per date column

// ── Colors ────────────────────────────────────────────────────────────────────
const C = {
    axis:           '#d0d0d0',
    tick:           '#aaa',
    stem:           '#e0e0e0',
    cardBg:         '#fff',
    cardBgSel:      '#fafafa',
    cardBorder:     '#ddd',
    cardSel:        '#111',
    textDate:       '#bbb',
    textTitle:      '#1a1a1a',
    // Node bar colors — semantic
    barOccurred:    '#10b981',  // green: confirmed event
    barPredicted:   '#94a3b8',  // slate: predicted/uncertain
    barPositive:    '#22c55e',  // bright green: positive impact on outcome
    barNegative:    '#ef4444',  // red: negative impact
    barMixed:       '#a855f7',  // purple: mixed
    barOutcome:     '#f59e0b',  // amber: outcome node
    // Link colors — semantic
    linkCauses:     '#10b981',
    linkEnables:    '#3b82f6',
    linkAmplifies:  '#22c55e',
    linkTriggers:   '#10b981',
    linkPrevents:   '#ef4444',
    linkInhibits:   '#f97316',
    linkPositive:   '#22c55e',
    linkNegative:   '#ef4444',
    linkMixed:      '#a855f7',
    linkDefault:    '#cbd5e1',
    // Outcome highlight
    outcomeRing:    '#f59e0b',
    outcomeGlow:    'rgba(245,158,11,0.15)',
}

function nodeBarColor(node) {
    // Actual outcome node — amber
    if (node.properties?.is_actual_outcome) return C.barOutcome
    // Impact direction (set by applyOutcomeAwareImpactColors)
    const dir = node._impactDirection
    if (dir === 'positive') return C.barPositive
    if (dir === 'negative') return C.barNegative
    if (dir === 'mixed')    return C.barMixed
    // Fallback: status
    const s = node.properties?.status || node.status
    if (s === 'occurred') return C.barOccurred
    return C.barPredicted
}

function nodeBorderColor(node, selected) {
    if (selected) return C.cardSel
    if (node.properties?.is_actual_outcome) return C.outcomeRing
    return C.cardBorder
}

function nodeBorderWidth(node, selected) {
    if (selected) return 1.5
    if (node.properties?.is_actual_outcome) return 2
    return 1
}

function linkColor(link) {
    const t = (link.relation_type || link.type || link.edge_type || '').toLowerCase().replace(/ /g, '_')
    if (t.includes('impact_positive') || t === 'amplifies' || t === 'causes' || t === 'triggers') return C.linkPositive
    if (t.includes('impact_negative') || t === 'prevents' || t === 'inhibits') return C.linkNegative
    if (t.includes('impact_mixed'))  return C.linkMixed
    if (t === 'enables')             return C.linkEnables
    return C.linkDefault
}

function parseDate(node) {
    // Try nested properties first, then top-level fields
    const s = node.properties?.occurred_date
        || node.properties?.predicted_date
        || node.properties?.date
        || node.occurred_date
        || node.predicted_date
        || node.date
        || node.event_date
    if (!s) return null
    const d = new Date(s)
    return isNaN(d) ? null : d
}

function fmtDate(d) {
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' })
}

// ── Layout engine ─────────────────────────────────────────────────────────────
function buildLayout(rawNodes, containerW) {
    // Group by day
    const byDay = {}
    for (const n of rawNodes) {
        const key = new Date(n._date).toDateString()
        ;(byDay[key] = byDay[key] || []).push(n)
    }

    // Sort day keys chronologically
    const dayKeys = Object.keys(byDay).sort((a, b) => new Date(a) - new Date(b))

    // Assign column X positions — spread evenly across containerW, min MIN_COL_W each
    const nCols  = dayKeys.length
    const colW   = Math.max(MIN_COL_W, containerW / nCols)
    const totalW = Math.max(containerW, nCols * colW)

    const axisY  = SVG_H - AXIS_BOT

    // Build node positions
    const laid = []
    const colInfo = {}   // key -> { x, nodes[] }

    dayKeys.forEach((key, ci) => {
        const cx = colW * ci + colW / 2
        colInfo[key] = { cx, nodes: byDay[key] }

        byDay[key].forEach((n, ni) => {
            // Stack upward from axis
            const cardBottom = axisY - TICK_H - (ni * (CARD_H + CARD_GAP)) - CARD_GAP
            const cy = cardBottom - CARD_H / 2
            laid.push({
                ...n,
                cx,
                cy,
                cardTop: cy - CARD_H / 2,
                cardBottom: cardBottom,
            })
        })
    })

    return { laid, totalW, axisY, colInfo, dayKeys, colW }
}

function generateTicks(dayKeys) {
    if (!dayKeys.length) return []
    const total = dayKeys.length
    // Show at most ~10 ticks evenly spaced
    const step  = Math.max(1, Math.round(total / 10))
    return dayKeys
        .filter((_, i) => i % step === 0 || i === total - 1)
        .map(key => ({ key, label: new Date(key).toLocaleDateString(undefined,
            total <= 14
                ? { month: 'short', day: 'numeric' }
                : total <= 90
                    ? { month: 'short', day: 'numeric' }
                    : total <= 730
                        ? { year: 'numeric', month: 'short' }
                        : { year: 'numeric' }
        )}))
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function CanvasTimelineGraph({ graphData, onNodeClick, selectedNode, timeFilter }) {
    const containerRef = useRef(null)
    const [contW, setContW] = useState(800)
    const [vZoom, setVZoom]       = useState(1)
    const [panX, setPanX]         = useState(0)
    const [isDragging, setIsDragging] = useState(false)
    const dragging = useRef(null)

    useEffect(() => {
        const el = containerRef.current
        if (!el) return
        const ro = new ResizeObserver(([e]) => setContW(e.contentRect.width))
        ro.observe(el)
        return () => ro.disconnect()
    }, [])

    const layout = useMemo(() => {
        if (!graphData?.nodes?.length) return null
        const raw = graphData.nodes
            .map(n => ({ ...n, _date: parseDate(n) }))
            .filter(n => n._date)
        // If no nodes have dates, try top-level date fields as fallback
        if (!raw.length) {
            const fallback = graphData.nodes
                .map(n => {
                    const s = n.occurred_date || n.predicted_date || n.date
                    const d = s ? new Date(s) : null
                    return { ...n, _date: d && !isNaN(d) ? d : null }
                })
                .filter(n => n._date)
            if (!fallback.length) return null
            return buildLayout(fallback, contW)
        }
        return buildLayout(raw, contW)
    }, [graphData, contW])

    const { nodes, links, ticks } = useMemo(() => {
        if (!layout) return { nodes: [], links: [], ticks: [] }
        const { laid, colInfo, dayKeys } = layout
        const nodeMap = new Map(laid.map(n => [n.id, n]))

        const resolvedLinks = (graphData.links || [])
            .map(l => ({
                ...l,
                source: nodeMap.get(l.source?.id || l.source),
                target: nodeMap.get(l.target?.id || l.target),
            }))
            .filter(l => l.source && l.target && l.source.id !== l.target.id
                && l.source.cx < l.target.cx)  // left-to-right only

        return { nodes: laid, links: resolvedLinks, ticks: generateTicks(dayKeys) }
    }, [layout, graphData])

    // Clamp panX so content never drifts entirely off-screen
    const clampPan = useCallback((x, totalW) => {
        const max = 0
        const min = Math.min(0, contW - totalW)
        return Math.max(min, Math.min(max, x))
    }, [contW])

    const onMouseDown = useCallback(e => {
        // Ignore clicks on cards (SVG <g> elements — use data attribute instead of .closest)
        if (e.target.dataset?.card) return
        dragging.current = { startX: e.clientX, startPan: panX }
        setIsDragging(true)
        e.currentTarget.setPointerCapture(e.pointerId)
    }, [panX])

    const onMouseMove = useCallback(e => {
        if (!dragging.current || !layout) return
        const dx = e.clientX - dragging.current.startX
        setPanX(clampPan(dragging.current.startPan + dx, layout.totalW))
    }, [clampPan, layout])

    const onMouseUp = useCallback(() => {
        dragging.current = null
        setIsDragging(false)
    }, [])

    // Reset pan when data changes
    useEffect(() => { setPanX(0) }, [graphData])

    const visible = useCallback(node => {
        if (!timeFilter?.start || !timeFilter?.end) return true
        return node._date >= timeFilter.start && node._date <= timeFilter.end
    }, [timeFilter])

    if (!layout || !nodes.length) {
        return (
            <div className="canvas-timeline-graph" ref={containerRef}>
                <div className="canvas-timeline-graph-empty">
                    <p>{!graphData?.nodes?.length
                        ? 'No graph data for this question.'
                        : 'No events with valid dates.'}</p>
                </div>
            </div>
        )
    }

    const { totalW, axisY, colInfo } = layout
    const svgH = SVG_H * vZoom

    return (
        <div
            className="canvas-timeline-graph"
            ref={containerRef}
            onPointerDown={onMouseDown}
            onPointerMove={onMouseMove}
            onPointerUp={onMouseUp}
            onPointerLeave={onMouseUp}
            style={{ cursor: isDragging ? 'grabbing' : 'grab', overflow: 'hidden' }}
        >
                <svg
                    width={contW}
                    height={svgH}
                    style={{ display: 'block' }}
                >
                    <g transform={`translate(${panX} 0)`}>
                    {/* ── Axis — extends full content width ── */}
                    <line x1={0} y1={axisY * vZoom} x2={totalW} y2={axisY * vZoom}
                        stroke={C.axis} strokeWidth={1} />

                    {/* ── Tick marks + labels ── */}
                    {ticks.map((t, i) => {
                        const col = colInfo[t.key]
                        if (!col) return null
                        const x = col.cx
                        const ay = axisY * vZoom
                        return (
                            <g key={i}>
                                <line x1={x} y1={ay - TICK_H} x2={x} y2={ay + TICK_H}
                                    stroke={C.tick} strokeWidth={1} />
                                <text x={x} y={ay + TICK_H + LABEL_H}
                                    textAnchor="middle" fontSize={9} fill={C.tick}
                                    fontFamily="Inter,sans-serif">
                                    {t.label}
                                </text>
                            </g>
                        )
                    })}

                    {/* ── Stems (card bottom → axis) ── */}
                    {nodes.filter(visible).map(n => {
                        const ay = axisY * vZoom
                        const cy = n.cy * vZoom
                        const cb = n.cardBottom * vZoom
                        return (
                            <line key={`stem-${n.id}`}
                                x1={n.cx} y1={cb}
                                x2={n.cx} y2={ay}
                                stroke={C.stem} strokeWidth={1} strokeDasharray="3 3" />
                        )
                    })}

                    {/* ── Causal links — route along axis ── */}
                    {links.filter(l => visible(l.source) && visible(l.target)).map((l, i) => {
                        const ay   = axisY * vZoom
                        const sx   = l.source.cx
                        const tx   = l.target.cx
                        const srcB = l.source.cardBottom * vZoom
                        const tgtB = l.target.cardBottom * vZoom
                        const col  = linkColor(l)
                        const isImpact = (l.relation_type || l.type || '').toLowerCase().includes('impact')
                        const d = `M ${sx} ${srcB} L ${sx} ${ay} L ${tx} ${ay} L ${tx} ${tgtB}`
                        return (
                            <g key={i} opacity={0.6}>
                                <path d={d} fill="none"
                                    stroke={col}
                                    strokeWidth={isImpact ? 1.5 : 1}
                                    strokeDasharray={isImpact ? '5 3' : undefined} />
                                <polygon
                                    points={`${tx},${tgtB - 1} ${tx - 5},${tgtB + 7} ${tx + 5},${tgtB + 7}`}
                                    fill={col} />
                            </g>
                        )
                    })}

                    {/* ── Cards ── */}
                    {nodes.filter(visible).map(n => {
                        const sel      = selectedNode?.id === n.id
                        const isOutcome = n.properties?.is_actual_outcome
                        const barCol   = nodeBarColor(n)
                        const borderCol = nodeBorderColor(n, sel)
                        const borderW  = nodeBorderWidth(n, sel)
                        const cy    = n.cy * vZoom
                        const x     = n.cx - CARD_W / 2
                        const y     = cy - CARD_H / 2
                        const title = n.name || n.title || n.id || ''
                        const short = title.length > 18 ? title.slice(0, 18) + '…' : title

                        return (
                            <g key={n.id} className="tl-card" data-card="1" style={{ cursor: 'pointer' }}
                                onClick={() => onNodeClick?.(n)}>
                                {/* Outcome glow ring */}
                                {isOutcome && (
                                    <rect x={x - 4} y={y - 4} width={CARD_W + 8} height={CARD_H + 8}
                                        rx={7} fill={C.outcomeGlow} stroke={C.outcomeRing}
                                        strokeWidth={1.5} strokeDasharray="4 2" />
                                )}
                                {/* Shadow */}
                                <rect x={x + 1} y={y + 1} width={CARD_W} height={CARD_H}
                                    rx={4} fill="rgba(0,0,0,0.05)" />
                                {/* Body */}
                                <rect x={x} y={y} width={CARD_W} height={CARD_H}
                                    rx={4}
                                    fill={C.cardBg}
                                    stroke={borderCol}
                                    strokeWidth={borderW} />
                                {/* Color bar — semantic */}
                                <rect x={x} y={y} width={CARD_W} height={3}
                                    rx={4} fill={barCol} />
                                {/* Date + outcome label */}
                                <text x={x + 7} y={y + 15} fontSize={8} fill={C.textDate}
                                    fontFamily="Inter,sans-serif">
                                    {fmtDate(n._date)}{isOutcome ? ' · OUTCOME' : ''}
                                </text>
                                {/* Title */}
                                <text x={x + 7} y={y + 30} fontSize={9.5}
                                    fill={isOutcome ? C.outcomeRing : C.textTitle}
                                    fontFamily="Inter,sans-serif" fontWeight={isOutcome ? 700 : 600}>
                                    {short}
                                </text>
                                <title>{title}</title>
                            </g>
                        )
                    })}
                    </g>
                </svg>

            <div className="graph-overlay-controls">
                <button className="control-btn" title="Expand vertically"
                    onClick={() => setVZoom(z => Math.min(3, +(z + 0.25).toFixed(2)))}>↕+</button>
                <button className="control-btn" title="Compress vertically"
                    onClick={() => setVZoom(z => Math.max(0.5, +(z - 0.25).toFixed(2)))}>↕−</button>
                <button className="control-btn" title="Reset"
                    onClick={() => { setVZoom(1); setPanX(0) }}>⟲</button>
            </div>
        </div>
    )
}
