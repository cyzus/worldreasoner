/**
 * CanvasTimelineGraph — SVG timeline visualization.
 *
 * Layout:
 *  - Horizontal time axis at vertical centre.
 *  - Nodes pinned to their date on X.
 *  - Nodes at the same date stack in columns above/below the axis.
 *  - Column height capped by available space; zoom out to see all.
 *  - Arrows routed via the axis (elbow path) to avoid crossing clutter.
 *  - Pan (drag) + zoom (wheel / buttons).
 */
import React, { useMemo, useState, useRef, useCallback, useEffect } from 'react'
import './CanvasTimelineGraph.css'

// ── Constants ─────────────────────────────────────────────────────────────────
const CARD_W    = 148   // card width
const CARD_H    = 44    // card height
const COL_GAP   = 6     // vertical gap between stacked cards
const AXIS_FRAC = 0.5   // axis at 50% of height
const PAD_X     = 60    // horizontal margin
const TICK_H    = 6
const MIN_ZOOM  = 0.15
const MAX_ZOOM  = 4

// ── Colors ────────────────────────────────────────────────────────────────────
const C = {
    axis:       '#c8c8c8',
    tick:       '#aaa',
    stem:       '#ddd',
    cardBg:     '#fff',
    cardBgSel:  '#f2f2f2',
    cardBorder: '#ddd',
    cardSel:    '#111',
    textDate:   '#aaa',
    textTitle:  '#1a1a1a',
    barOccurred:'#555',
    barDefault: '#bbb',
    barOutcome: '#111',
    link:       '#bbb',
    linkCausal: '#888',
    arrow:      '#888',
}

function nodeBarColor(node) {
    if (node.properties?.is_actual_outcome) return C.barOutcome
    const s = node.properties?.status || node.status
    if (s === 'occurred') return C.barOccurred
    return C.barDefault
}

function parseDate(node) {
    const s = node.properties?.occurred_date || node.properties?.predicted_date
        || node.occurred_date || node.predicted_date
    if (!s) return null
    const d = new Date(s)
    return isNaN(d) ? null : d
}

function generateTicks(minMs, maxMs) {
    const days = (maxMs - minMs) / 86400000
    let stepDays, fmt
    if      (days <= 14)  { stepDays = 1;   fmt = d => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) }
    else if (days <= 90)  { stepDays = 7;   fmt = d => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) }
    else if (days <= 730) { stepDays = 30;  fmt = d => d.toLocaleDateString(undefined, { year: 'numeric', month: 'short' }) }
    else                  { stepDays = 365; fmt = d => String(d.getFullYear()) }

    const ticks = []
    const cur = new Date(minMs); cur.setHours(0,0,0,0)
    while (cur.getTime() <= maxMs) {
        ticks.push({ ms: cur.getTime(), label: fmt(cur) })
        cur.setDate(cur.getDate() + stepDays)
    }
    return ticks
}

// ── Layout ────────────────────────────────────────────────────────────────────
function layoutNodes(rawNodes, svgW, svgH) {
    const axisY    = svgH * AXIS_FRAC
    const halfH    = axisY          // space above axis
    const halfB    = svgH - axisY   // space below axis

    const times    = rawNodes.map(n => n._date.getTime())
    const minMs    = Math.min(...times)
    const maxMs    = Math.max(...times)
    const span     = maxMs - minMs || 86400000
    const usableW  = svgW - PAD_X * 2
    const toX      = ms => PAD_X + ((ms - minMs) / span) * usableW

    // Group by day
    const byDay = {}
    for (const n of rawNodes) {
        const key = new Date(n._date).toDateString()
        if (!byDay[key]) byDay[key] = []
        byDay[key].push(n)
    }

    // Max lanes that fit above/below
    const maxAbove = Math.max(1, Math.floor((halfH - 30) / (CARD_H + COL_GAP)))
    const maxBelow = Math.max(1, Math.floor((halfB - 30) / (CARD_H + COL_GAP)))

    const laid = []
    for (const [, group] of Object.entries(byDay)) {
        const cx = toX(group[0]._date.getTime())
        group.forEach((n, idx) => {
            const above = idx % 2 === 0
            const lane  = Math.floor(idx / 2) // 0-based lane index
            // Skip nodes beyond max lanes (will show "+N" badge on last)
            const maxLane = above ? maxAbove - 1 : maxBelow - 1
            const hidden  = lane > maxLane

            const laneY = lane * (CARD_H + COL_GAP) + CARD_H / 2 + COL_GAP
            const cy = above
                ? axisY - laneY
                : axisY + laneY

            laid.push({ ...n, cx, cy, above, lane, hidden, _dayKey: new Date(n._date).toDateString() })
        })
    }

    // "+N" overflow badges per day
    const overflow = {}
    for (const [key, group] of Object.entries(byDay)) {
        const maxAboveSlots = maxAbove
        const maxBelowSlots = maxBelow
        let hiddenCount = 0
        group.forEach((_, idx) => {
            const above = idx % 2 === 0
            const lane  = Math.floor(idx / 2)
            if (above && lane >= maxAboveSlots) hiddenCount++
            if (!above && lane >= maxBelowSlots) hiddenCount++
        })
        if (hiddenCount > 0) {
            const cx = toX(group[0]._date.getTime())
            overflow[key] = { cx, hiddenCount }
        }
    }

    return { laid: laid.filter(n => !n.hidden), overflow, axisY, toX, minMs, maxMs }
}

// ── Elbow arrow path ──────────────────────────────────────────────────────────
// Routes via the axis line to avoid crossing cards.
function elbowPath(sx, sy, tx, ty, axisY) {
    // Mid-X between source right edge and target left edge
    const mx = (sx + tx) / 2
    // If both cards are on the same side, route straight with a small bend
    if ((sy < axisY && ty < axisY) || (sy > axisY && ty > axisY)) {
        return `M ${sx} ${sy} C ${mx} ${sy} ${mx} ${ty} ${tx} ${ty}`
    }
    // Cross-axis: dip down to axis, travel, come back up
    return `M ${sx} ${sy} L ${sx} ${axisY} L ${tx} ${axisY} L ${tx} ${ty}`
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function CanvasTimelineGraph({ graphData, onNodeClick, selectedNode, timeFilter }) {
    const containerRef = useRef(null)
    const [size, setSize] = useState({ w: 900, h: 500 })
    const [pan,  setPan]  = useState({ x: 0, y: 0 })
    const [zoom, setZoom] = useState(1)
    const dragging = useRef(null)
    const [hovered, setHovered] = useState(null)

    useEffect(() => {
        if (!containerRef.current) return
        const ro = new ResizeObserver(([e]) => {
            setSize({ w: e.contentRect.width, h: e.contentRect.height })
        })
        ro.observe(containerRef.current)
        return () => ro.disconnect()
    }, [])

    const layout = useMemo(() => {
        if (!graphData?.nodes?.length) return null
        const raw = graphData.nodes.map(n => ({ ...n, _date: parseDate(n) })).filter(n => n._date)
        if (!raw.length) return null
        return layoutNodes(raw, size.w, size.h)
    }, [graphData, size])

    const { nodes, links, ticks } = useMemo(() => {
        if (!layout) return { nodes: [], links: [], ticks: [] }
        const { laid, toX, minMs, maxMs } = layout
        const nodeMap = new Map(laid.map(n => [n.id, n]))

        const resolvedLinks = (graphData.links || [])
            .map(l => ({
                ...l,
                source: nodeMap.get(l.source?.id || l.source),
                target: nodeMap.get(l.target?.id || l.target),
            }))
            .filter(l => l.source && l.target && l.source.id !== l.target.id)

        const tks = generateTicks(minMs, maxMs)
        return { nodes: laid, links: resolvedLinks, ticks: tks }
    }, [layout, graphData])

    const visible = useCallback(node => {
        if (!timeFilter?.start || !timeFilter?.end) return true
        return node._date >= timeFilter.start && node._date <= timeFilter.end
    }, [timeFilter])

    useEffect(() => { setPan({ x: 0, y: 0 }); setZoom(1) }, [graphData])

    const onWheel = useCallback(e => {
        e.preventDefault()
        const factor = e.deltaY > 0 ? 0.88 : 1.14
        setZoom(z => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z * factor)))
    }, [])

    const onMouseDown = useCallback(e => {
        if (e.target.closest('.tl-card')) return
        dragging.current = { sx: e.clientX - pan.x, sy: e.clientY - pan.y }
    }, [pan])

    const onMouseMove = useCallback(e => {
        if (!dragging.current) return
        setPan({ x: e.clientX - dragging.current.sx, y: e.clientY - dragging.current.sy })
    }, [])

    const onMouseUp = useCallback(() => { dragging.current = null }, [])

    if (!layout || !nodes.length) {
        return (
            <div className="canvas-timeline-graph" ref={containerRef}>
                <div className="canvas-timeline-graph-empty">
                    <p>{!graphData?.nodes?.length ? 'No graph data for this question.' : 'No events with valid dates.'}</p>
                </div>
            </div>
        )
    }

    const { axisY, toX, minMs, maxMs, overflow } = layout
    const span    = (maxMs - minMs) || 86400000
    const usableW = size.w - PAD_X * 2

    // SVG coordinate origin for zoom: centre of visible area
    const originX = size.w / 2
    const originY = size.h / 2

    return (
        <div
            className="canvas-timeline-graph"
            ref={containerRef}
            onWheel={onWheel}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
            style={{ cursor: dragging.current ? 'grabbing' : 'grab' }}
        >
            <svg width={size.w} height={size.h}>
                {/* clip so cards don't escape viewport */}
                <defs>
                    <clipPath id="tl-clip">
                        <rect x={0} y={0} width={size.w} height={size.h} />
                    </clipPath>
                </defs>

                <g clipPath="url(#tl-clip)">
                <g transform={`translate(${originX + pan.x} ${originY + pan.y}) scale(${zoom}) translate(${-originX} ${-originY})`}>

                    {/* Axis */}
                    <line x1={PAD_X / 2} y1={axisY} x2={size.w - PAD_X / 2} y2={axisY}
                        stroke={C.axis} strokeWidth={1} />

                    {/* Ticks */}
                    {ticks.map((t, i) => {
                        const x = PAD_X + ((t.ms - minMs) / span) * usableW
                        return (
                            <g key={i}>
                                <line x1={x} y1={axisY - TICK_H} x2={x} y2={axisY + TICK_H}
                                    stroke={C.tick} strokeWidth={1} />
                                <text x={x} y={axisY + TICK_H + 13}
                                    textAnchor="middle" fontSize={9} fill={C.tick}
                                    fontFamily="Inter,sans-serif">
                                    {t.label}
                                </text>
                            </g>
                        )
                    })}

                    {/* Stems (node → axis) */}
                    {nodes.filter(visible).map(n => (
                        <line key={`s-${n.id}`}
                            x1={n.cx}
                            y1={n.above ? n.cy + CARD_H / 2 : n.cy - CARD_H / 2}
                            x2={n.cx} y2={axisY}
                            stroke={C.stem} strokeWidth={1} strokeDasharray="3 3" />
                    ))}

                    {/* Causal links — routed via axis */}
                    {links.filter(l => visible(l.source) && visible(l.target)).map((l, i) => {
                        const isImpact = (l.relation_type || l.type || '').toLowerCase().includes('impact')
                        const sx = l.source.cx + CARD_W / 2
                        const sy = l.source.cy
                        const tx = l.target.cx - CARD_W / 2
                        const ty = l.target.cy
                        if (tx <= sx + 4) return null  // skip backward/same-position links
                        const d = elbowPath(sx, sy, tx, ty, axisY)
                        // arrowhead direction
                        const adx = tx - Math.max(sx, tx - 12)
                        return (
                            <g key={i} opacity={0.55}>
                                <path d={d} fill="none"
                                    stroke={isImpact ? C.linkCausal : C.link}
                                    strokeWidth={isImpact ? 1.5 : 1}
                                    strokeDasharray={isImpact ? '5 3' : undefined} />
                                <polygon
                                    points={`${tx},${ty} ${tx-8},${ty-4} ${tx-8},${ty+4}`}
                                    fill={isImpact ? C.linkCausal : C.link} />
                            </g>
                        )
                    })}

                    {/* Overflow badges */}
                    {Object.entries(overflow).map(([key, { cx, hiddenCount }]) => (
                        <g key={`ov-${key}`}>
                            <rect x={cx - 20} y={axisY - 14} width={40} height={18}
                                rx={9} fill="#eee" stroke="#ccc" strokeWidth={1} />
                            <text x={cx} y={axisY - 2}
                                textAnchor="middle" fontSize={9} fill="#888"
                                fontFamily="Inter,sans-serif">
                                +{hiddenCount}
                            </text>
                        </g>
                    ))}

                    {/* Cards */}
                    {nodes.filter(visible).map(n => {
                        const sel   = selectedNode?.id === n.id
                        const color = nodeBarColor(n)
                        const x     = n.cx - CARD_W / 2
                        const y     = n.cy - CARD_H / 2
                        const title = n.name || n.title || n.id || ''
                        const maxCh = 20
                        const shortTitle = title.length > maxCh ? title.slice(0, maxCh) + '…' : title
                        const dateStr = n._date.toLocaleDateString(undefined,
                            { month: 'short', day: 'numeric', year: '2-digit' })

                        return (
                            <g key={n.id} className="tl-card"
                                style={{ cursor: 'pointer' }}
                                onClick={() => onNodeClick?.(n)}
                                onMouseEnter={() => setHovered(n.id)}
                                onMouseLeave={() => setHovered(null)}
                            >
                                {/* Shadow */}
                                <rect x={x+2} y={y+2} width={CARD_W} height={CARD_H}
                                    rx={4} fill="rgba(0,0,0,0.05)" />
                                {/* Body */}
                                <rect x={x} y={y} width={CARD_W} height={CARD_H}
                                    rx={4}
                                    fill={sel ? C.cardBgSel : C.cardBg}
                                    stroke={sel ? C.cardSel : C.cardBorder}
                                    strokeWidth={sel ? 1.5 : 1} />
                                {/* Color bar */}
                                <rect x={x} y={y} width={CARD_W} height={3}
                                    rx={4} fill={color} />
                                {/* Date */}
                                <text x={x+8} y={y+16} fontSize={8.5} fill={C.textDate}
                                    fontFamily="Inter,sans-serif" fontWeight={500}>
                                    {dateStr}
                                </text>
                                {/* Title */}
                                <text x={x+8} y={y+31} fontSize={10} fill={C.textTitle}
                                    fontFamily="Inter,sans-serif" fontWeight={600}>
                                    {shortTitle}
                                </text>
                                {/* Native tooltip for full title */}
                                <title>{title}</title>
                            </g>
                        )
                    })}

                </g>
                </g>
            </svg>

            {/* Zoom controls */}
            <div className="graph-overlay-controls">
                <button className="control-btn" title="Reset"
                    onClick={() => { setPan({ x: 0, y: 0 }); setZoom(1) }}>⟲</button>
                <button className="control-btn" title="Zoom in"
                    onClick={() => setZoom(z => Math.min(MAX_ZOOM, z * 1.2))}>+</button>
                <button className="control-btn" title="Zoom out"
                    onClick={() => setZoom(z => Math.max(MIN_ZOOM, z * 0.83))}>−</button>
            </div>
        </div>
    )
}
