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
import EventDetails from './EventDetails'
import './CanvasTimelineGraph.css'

// ── Layout constants ──────────────────────────────────────────────────────────
const CARD_W    = 130   // card width px
const CARD_H    = 40    // card height px
const CARD_GAP  = 6     // vertical gap between stacked cards
const COL_PAD   = 20    // min horizontal padding between columns
const AXIS_BOT  = 60    // px below axis to bottom of SVG (tick labels)
const TICK_H    = 5
const LABEL_H   = 16    // height of tick label below axis
const CARD_TOP_PAD = 24 // min padding above topmost card
const MIN_COL_W = CARD_W + COL_PAD  // min width per date column
const VIEW_H_DEFAULT = 400  // fallback before ResizeObserver fires

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
// axisY is placed at 78% of viewH so cards are visible with balanced whitespace.
// If the tallest stack overflows above that, svgH grows and panY lets the user
// scroll up to see the clipped cards.
function buildLayout(rawNodes, containerW, viewH = VIEW_H_DEFAULT) {
    const byDay = {}
    for (const n of rawNodes) {
        const key = new Date(n._date).toDateString()
        ;(byDay[key] = byDay[key] || []).push(n)
    }

    const dayKeys = Object.keys(byDay).sort((a, b) => new Date(a) - new Date(b))
    const nCols   = dayKeys.length
    const colW    = Math.max(MIN_COL_W, containerW / nCols)
    const totalW  = Math.max(containerW, nCols * colW)

    // Place axis at 60% down the viewport
    const axisY = Math.round(viewH * 0.60)

    // How much vertical space do cards need above the axis?
    const maxStack = Math.max(...dayKeys.map(k => byDay[k].length))
    const stackH   = maxStack * (CARD_H + CARD_GAP) + CARD_GAP + TICK_H + CARD_TOP_PAD

    // SVG canvas must be at least viewH; grow upward if cards overflow
    const svgH = Math.max(viewH, stackH + AXIS_BOT)

    // If svgH > viewH the axis must shift down by the overflow amount
    // so it stays at the same screen position when panY=0
    const axisYFinal = axisY + (svgH - viewH)

    const laid    = []
    const colInfo = {}

    dayKeys.forEach((key, ci) => {
        const cx = colW * ci + colW / 2
        colInfo[key] = { cx, nodes: byDay[key] }

        byDay[key].forEach((n, ni) => {
            const cardBottom = axisYFinal - TICK_H - (ni * (CARD_H + CARD_GAP)) - CARD_GAP
            const cy         = cardBottom - CARD_H / 2
            laid.push({ ...n, cx, cy, cardTop: cy - CARD_H / 2, cardBottom })
        })
    })

    return { laid, totalW, svgH, axisY: axisYFinal, colInfo, dayKeys, colW }
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
export default function CanvasTimelineGraph({ graphData, onNodeClick, selectedNode, timeFilter, onShowNeighborhood }) {
    const containerRef = useRef(null)
    const [contW, setContW]           = useState(800)
    const [contH, setContH]           = useState(400)
    const [panX, setPanX]             = useState(0)
    const [panY, setPanY]             = useState(0)
    const [isDragging, setIsDragging] = useState(false)
    const [panel, setPanel]           = useState(null)
    const dragging = useRef(null)

    useEffect(() => {
        const el = containerRef.current
        if (!el) return
        let raf = null
        const ro = new ResizeObserver(([e]) => {
            if (raf) cancelAnimationFrame(raf)
            raf = requestAnimationFrame(() => {
                setContW(e.contentRect.width)
                setContH(e.contentRect.height)
            })
        })
        ro.observe(el)
        return () => { ro.disconnect(); if (raf) cancelAnimationFrame(raf) }
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
            return buildLayout(fallback, contW, contH)
        }
        return buildLayout(raw, contW, contH)
    }, [graphData, contW, contH])

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

        return { nodes: laid, links: resolvedLinks, ticks: generateTicks(dayKeys), nodeMap }
    }, [layout, graphData])

    // IDs of nodes connected to the selected panel node
    const connectedIds = useMemo(() => {
        if (!panel?.node || !links.length) return new Set()
        const nid = panel.node.id
        const ids = new Set()
        links.forEach(l => {
            const sid = l.source?.id || l.source
            const tid = l.target?.id || l.target
            if (sid === nid) ids.add(tid)
            if (tid === nid) ids.add(sid)
        })
        return ids
    }, [panel, links])

    const clampX = useCallback((x, totalW) =>
        Math.max(Math.min(0, contW - totalW), Math.min(0, x))
    , [contW])

    const clampY = useCallback((y, svgH) => {
        // Always allow at least ±(contH * 0.5) of drag travel so vertical
        // panning works even when content fits within the viewport.
        const slack = contH * 0.5
        const minY = Math.min(contH - svgH, -slack)
        const maxY = Math.max(0, slack)
        return Math.max(minY, Math.min(maxY, y))
    }, [contH])

    const onMouseDown = useCallback(e => {
        if (e.target.closest?.('[data-card]')) return
        setPanel(null)
        onNodeClick?.(null)
        dragging.current = { startX: e.clientX, startY: e.clientY, startPanX: panX, startPanY: panY, moved: false }
    }, [panX, panY, onNodeClick])

    const onMouseMove = useCallback(e => {
        if (!dragging.current || !layout) return
        const dx = e.clientX - dragging.current.startX
        const dy = e.clientY - dragging.current.startY
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
            dragging.current.moved = true
            setIsDragging(true)
            setPanX(clampX(dragging.current.startPanX + dx, layout.totalW))
            setPanY(clampY(dragging.current.startPanY + dy, layout.svgH))
        }
    }, [clampX, clampY, layout])

    const onMouseUp = useCallback(() => {
        dragging.current = null
        setIsDragging(false)
    }, [])

    // Scroll to show the bottom of the canvas (where axis and cards are).
    // The axis was already placed at 78% of contH in buildLayout, so
    // when svgH == contH panY=0 is perfect. When svgH > contH (overflow),
    // pan up by the extra height so the axis stays on screen.
    useEffect(() => {
        if (!layout) return
        setPanX(0)
        setPanY(-(layout.svgH - contH))
    }, [layout, contH])

    const visible = useCallback(node => {
        if (!timeFilter?.start || !timeFilter?.end) return true
        return node._date >= timeFilter.start && node._date <= timeFilter.end
    }, [timeFilter])

    // Wheel handler must be non-passive to call preventDefault (blocks page scroll)
    // Attach via useEffect so we can pass { passive: false }
    const onWheelRef = useRef(null)
    onWheelRef.current = useCallback(e => {
        e.preventDefault()
        if (!layout) return
        if (e.shiftKey) {
            // Shift+scroll → horizontal pan
            setPanX(prev => clampX(prev - e.deltaY * 1.5, layout.totalW))
        } else {
            // Default scroll → vertical pan
            setPanY(prev => clampY(prev - e.deltaY, layout.svgH))
        }
    }, [layout, clampX, clampY])

    useEffect(() => {
        const el = containerRef.current
        if (!el) return
        const handler = (e) => onWheelRef.current?.(e)
        el.addEventListener('wheel', handler, { passive: false })
        return () => el.removeEventListener('wheel', handler)
    }, []) // stable — handler is looked up via ref each time

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

    const { totalW, svgH, axisY, colInfo } = layout

    return (
        <div
            className="canvas-timeline-graph"
            ref={containerRef}
            onMouseDown={onMouseDown}
            onMouseMove={onMouseMove}
            onMouseUp={onMouseUp}
            onMouseLeave={onMouseUp}
            style={{ cursor: isDragging ? 'grabbing' : 'grab', overflow: 'hidden' }}
        >
                <svg
                    width={contW}
                    height={contH}
                    style={{ display: 'block' }}
                >
                    <g transform={`translate(${panX} ${panY})`}>
                    {/* ── Axis — extends full content width ── */}
                    <line x1={0} y1={axisY} x2={totalW} y2={axisY}
                        stroke={C.axis} strokeWidth={1} />

                    {/* ── Tick marks + labels ── */}
                    {ticks.map((t, i) => {
                        const col = colInfo[t.key]
                        if (!col) return null
                        const x = col.cx
                        return (
                            <g key={i}>
                                <line x1={x} y1={axisY - TICK_H} x2={x} y2={axisY + TICK_H}
                                    stroke={C.tick} strokeWidth={1} />
                                <text x={x} y={axisY + TICK_H + LABEL_H}
                                    textAnchor="middle" fontSize={9} fill={C.tick}
                                    fontFamily="Inter,sans-serif">
                                    {t.label}
                                </text>
                            </g>
                        )
                    })}

                    {/* ── Stems (card bottom → axis) ── */}
                    {nodes.filter(visible).map(n => (
                        <line key={`stem-${n.id}`}
                            x1={n.cx} y1={n.cardBottom}
                            x2={n.cx} y2={axisY}
                            stroke={C.stem} strokeWidth={1} strokeDasharray="3 3" />
                    ))}

                    {/* ── Causal links — cubic bezier curves ── */}
                    {links.filter(l => visible(l.source) && visible(l.target)).map((l, i) => {
                        const sid = l.source.id; const tid = l.target.id
                        const pid = panel?.node?.id
                        const isActive = pid && (sid === pid || tid === pid)
                        const sx   = l.source.cx + CARD_W / 2
                        const sy   = l.source.cardBottom
                        const tx   = l.target.cx - CARD_W / 2
                        const ty   = l.target.cardBottom
                        const col  = linkColor(l)
                        const isImpact = (l.relation_type || l.type || '').toLowerCase().includes('impact')
                        const curveDip = Math.min(60, (axisY - Math.min(sy, ty)) * 0.6)
                        const cy1 = sy + curveDip
                        const cy2 = ty + curveDip
                        const mx  = (sx + tx) / 2
                        const d   = `M ${sx} ${sy} C ${mx} ${cy1}, ${mx} ${cy2}, ${tx} ${ty}`
                        const angle = Math.atan2(ty - cy2, tx - mx)
                        const aLen = 7
                        const ax1 = tx - aLen * Math.cos(angle - 0.4)
                        const ay1 = ty - aLen * Math.sin(angle - 0.4)
                        const ax2 = tx - aLen * Math.cos(angle + 0.4)
                        const ay2 = ty - aLen * Math.sin(angle + 0.4)
                        // Dim non-active links when something is expanded
                        const opacity = panel ? (isActive ? 0.9 : 0.15) : 0.65
                        const strokeW = isActive ? (isImpact ? 2.5 : 2) : (isImpact ? 1.5 : 1)

                        return (
                            <g key={i} opacity={opacity}>
                                <path d={d} fill="none" stroke={col}
                                    strokeWidth={strokeW}
                                    strokeDasharray={isImpact ? '5 3' : undefined} />
                                <polygon points={`${tx},${ty} ${ax1},${ay1} ${ax2},${ay2}`}
                                    fill={col} />
                            </g>
                        )
                    })}

                    {/* ── Cards ── */}
                    {nodes.filter(visible).map(n => {
                        const isSelected  = panel?.node?.id === n.id
                        const isConnected = connectedIds.has(n.id)
                        const isOutcome   = n.properties?.is_actual_outcome
                        const barCol      = nodeBarColor(n)
                        const cy  = n.cy
                        const x   = n.cx - CARD_W / 2
                        const y   = cy - CARD_H / 2
                        const title = n.name || n.title || n.id || ''
                        const short = title.length > 18 ? title.slice(0, 18) + '…' : title

                        const borderCol = isSelected  ? '#111'
                            : isConnected             ? barCol
                            : isOutcome               ? C.outcomeRing
                            : C.cardBorder
                        const borderW = isSelected ? 2 : (isConnected || isOutcome) ? 1.5 : 1

                        return (
                            <g key={n.id} className="tl-card" data-card="1" style={{ cursor: 'pointer' }}
                                onClick={() => {
                                    if (isSelected) {
                                        setPanel(null); onNodeClick?.(null)
                                    } else {
                                        // Compute viewport coords for useDraggablePopup
                                        const rect = containerRef.current?.getBoundingClientRect() || { left: 0, top: 0 }
                                        const screenX = rect.left + n.cx + CARD_W / 2 + panX
                                        const screenY = rect.top + cy + panY
                                        const nodeWithCoords = { ...n, _screenX: screenX, _screenY: screenY }
                                        setPanel({ node: nodeWithCoords })
                                        onNodeClick?.(nodeWithCoords)
                                    }
                                }}>
                                {/* Outcome glow */}
                                {isOutcome && (
                                    <rect x={x - 4} y={y - 4} width={CARD_W + 8} height={CARD_H + 8}
                                        rx={7} fill={C.outcomeGlow} stroke={C.outcomeRing}
                                        strokeWidth={1.5} strokeDasharray="4 2" />
                                )}
                                {/* Connected ring */}
                                {isConnected && !isSelected && (
                                    <rect x={x - 3} y={y - 3} width={CARD_W + 6} height={CARD_H + 6}
                                        rx={6} fill="none" stroke={barCol} strokeWidth={1} opacity={0.5} />
                                )}
                                {/* Shadow */}
                                <rect x={x + 1} y={y + 2} width={CARD_W} height={CARD_H}
                                    rx={4} fill="rgba(0,0,0,0.06)" />
                                {/* Body */}
                                <rect x={x} y={y} width={CARD_W} height={CARD_H}
                                    rx={4} fill={C.cardBg} stroke={borderCol} strokeWidth={borderW} />
                                {/* Color bar */}
                                <rect x={x} y={y} width={CARD_W} height={3} rx={4} fill={barCol} />
                                {/* Date */}
                                <text x={x + 8} y={y + 15} fontSize={8} fill={C.textDate}
                                    fontFamily="Inter,sans-serif">
                                    {fmtDate(n._date)}{isOutcome ? ' · OUTCOME' : ''}
                                </text>
                                {/* Title */}
                                <text x={x + 8} y={y + 30} fontSize={9.5}
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

            {/* EventDetails — stop mousedown propagation so panel clicks don't close the panel */}
            {panel && (
                <div onMouseDown={e => e.stopPropagation()} onClick={e => e.stopPropagation()}>
                    <EventDetails
                        node={panel.node}
                        onClose={() => { setPanel(null); onNodeClick?.(null) }}
                        onShowNeighborhood={onShowNeighborhood}
                    />
                </div>
            )}

            <div className="graph-overlay-controls">
                <span className="control-hint">scroll ↕ · shift+scroll ↔ · drag freely</span>
                <button className="control-btn" title="Reset view"
                    onClick={() => {
                        setPanX(0)
                        setPanY(-(svgH - contH))
                    }}>⟲</button>
            </div>
        </div>
    )
}
