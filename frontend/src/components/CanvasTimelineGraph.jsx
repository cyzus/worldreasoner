/**
 * CanvasTimelineGraph - High-performance canvas-based event timeline visualization
 * 
 * Uses react-force-graph-2d for canvas rendering with:
 * - Date-based X positioning (timeline layout)
 * - Collision-based Y spacing
 * - Zoom-aware LOD (dots → cards)
 */
import React, { useRef, useEffect, useState, useMemo, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import * as d3 from 'd3'
import { GraphStyles } from '../styles/GraphStyles'
import { GraphLegend } from '../utils/graphRendering.jsx'
import './CanvasTimelineGraph.css'

/**
 * Calculate the point on a rectangle's edge where a line from center at given angle intersects
 * Uses ray-box intersection without tan() to avoid numerical issues
 */
const getRectEdgePoint = (cx, cy, width, height, angle) => {
    const hw = width / 2
    const hh = height / 2

    // Direction vector from angle
    const dx = Math.cos(angle)
    const dy = Math.sin(angle)

    // Handle edge cases where direction is near-zero
    const absDx = Math.abs(dx)
    const absDy = Math.abs(dy)

    if (absDx < 0.0001 && absDy < 0.0001) {
        return { x: cx, y: cy }  // No direction, return center
    }

    // Calculate t for intersection with each edge
    // For a ray from center: point = center + t * direction
    // We want the intersection point on the rectangle boundary

    let t
    if (absDx < 0.0001) {
        // Nearly vertical line - intersects top or bottom
        t = hh / absDy
    } else if (absDy < 0.0001) {
        // Nearly horizontal line - intersects left or right
        t = hw / absDx
    } else {
        // General case: find which edge is hit first
        const tHorizontal = hw / absDx  // Time to hit left/right edge
        const tVertical = hh / absDy    // Time to hit top/bottom edge
        t = Math.min(tHorizontal, tVertical)
    }

    return {
        x: cx + dx * t,
        y: cy + dy * t
    }
}

const CanvasTimelineGraph = ({
    graphData,
    onNodeClick,
    selectedNode,
    targetEventId,
    timeFilter = null
}) => {
    const containerRef = useRef(null)
    const graphRef = useRef(null)
    const [dimensions, setDimensions] = useState({ width: 800, height: 600 })
    const [currentZoom, setCurrentZoom] = useState(1)

    // Configuration
    const NODE_BASE_SIZE = 6
    const NODE_TARGET_SIZE = 10
    const CARD_MIN_ZOOM = 0.8  // Show cards above this zoom
    const CARD_WIDTH = 140
    const CARD_HEIGHT = 50

    // Responsive dimensions
    useEffect(() => {
        if (!containerRef.current) return
        const updateDimensions = () => {
            if (containerRef.current) {
                const { clientWidth, clientHeight } = containerRef.current
                setDimensions(prev => {
                    if (prev.width === clientWidth && prev.height === clientHeight) return prev
                    return { width: clientWidth, height: clientHeight }
                })
            }
        }
        updateDimensions()
        const observer = new ResizeObserver(updateDimensions)
        observer.observe(containerRef.current)
        return () => observer.disconnect()
    }, [])

    // Process graph data with date positions
    const processedData = useMemo(() => {
        if (!graphData?.nodes?.length) {
            return { nodes: [], links: [] }
        }

        // Parse dates and filter valid nodes
        const nodesWithDates = graphData.nodes
            .map(n => {
                const dateStr = n.properties?.occurred_date || n.properties?.predicted_date ||
                    n.occurred_date || n.predicted_date
                const date = dateStr ? new Date(dateStr) : null
                return { ...n, _date: date }
            })
            .filter(n => n._date && !isNaN(n._date))

        if (nodesWithDates.length === 0) {
            return { nodes: [], links: [] }
        }

        // Calculate time scale
        const dates = nodesWithDates.map(n => n._date)
        const minDate = d3.min(dates)
        const maxDate = d3.max(dates)
        const span = maxDate - minDate || 86400000

        // Create time scale for X positioning
        const timeScale = d3.scaleTime()
            .domain([new Date(minDate - span * 0.05), new Date(maxDate.getTime() + span * 0.05)])
            .range([100, dimensions.width - 100])

        // Assign fixed X positions based on date
        const nodes = nodesWithDates.map(n => ({
            ...n,
            fx: timeScale(n._date),  // Fixed X position
            // Initial Y with jitter
            y: dimensions.height / 2 + (Math.random() - 0.5) * 200
        }))

        // Build node map for link resolution
        const nodeMap = new Map(nodes.map(n => [n.id, n]))

        // Filter and resolve links
        const links = (graphData.links || [])
            .filter(l => {
                const sourceId = l.source?.id || l.source
                const targetId = l.target?.id || l.target
                return nodeMap.has(sourceId) && nodeMap.has(targetId)
            })
            .map(l => ({
                ...l,
                source: l.source?.id || l.source,
                target: l.target?.id || l.target
            }))

        return { nodes, links, timeScale }
    }, [graphData, dimensions.width])

    // Get node color based on status
    const getNodeColor = useCallback((node) => {
        if (node.isOutcome || node.id === targetEventId) {
            return GraphStyles.nodeColors.target
        }
        const status = node.properties?.status || node.status
        if (status === 'occurred') {
            return '#10b981'  // Green
        }
        if (status === 'predicted' || status === 'uncertain') {
            return '#3b82f6'  // Blue
        }
        // Fallback: past = green, future = blue
        if (node._date && node._date < new Date()) {
            return '#10b981'
        }
        return '#3b82f6'
    }, [targetEventId])

    // Get link color based on relation type
    const getLinkColor = useCallback((link) => {
        const type = (link.relation_type || link.type || 'default').toLowerCase().replace(/ /g, '_')
        return GraphStyles.linkColors[type] || GraphStyles.linkColors.default || '#94a3b8'
    }, [])

    // Check if node is visible based on time filter
    const isNodeVisible = useCallback((node) => {
        if (!timeFilter?.start || !timeFilter?.end) return true
        if (!node._date) return false
        return node._date >= timeFilter.start && node._date <= timeFilter.end
    }, [timeFilter])

    // Custom node painting
    const paintNode = useCallback((node, ctx, globalScale) => {
        // Validate coordinates first - skip if not ready
        if (!node.x || !node.y || !isFinite(node.x) || !isFinite(node.y)) {
            return
        }

        if (!isNodeVisible(node)) {
            return  // Skip invisible nodes
        }

        const isTarget = node.isOutcome || node.id === targetEventId
        const isSelected = selectedNode?.id === node.id
        const size = isTarget ? NODE_TARGET_SIZE : NODE_BASE_SIZE
        const color = getNodeColor(node)
        const showCard = globalScale >= CARD_MIN_ZOOM

        // Draw glow for target/selected
        if (isTarget || isSelected) {
            ctx.beginPath()
            ctx.arc(node.x, node.y, size + (showCard ? 25 : 8), 0, 2 * Math.PI)
            const gradient = ctx.createRadialGradient(
                node.x, node.y, size,
                node.x, node.y, size + (showCard ? 25 : 8)
            )
            if (isTarget) {
                gradient.addColorStop(0, 'rgba(255, 215, 0, 0.4)')
                gradient.addColorStop(1, 'rgba(255, 215, 0, 0)')
            } else {
                gradient.addColorStop(0, 'rgba(59, 130, 246, 0.3)')
                gradient.addColorStop(1, 'rgba(59, 130, 246, 0)')
            }
            ctx.fillStyle = gradient
            ctx.fill()
        }

        if (showCard) {
            // Card mode - draw rounded rectangle
            const cardW = CARD_WIDTH / globalScale
            const cardH = CARD_HEIGHT / globalScale
            const radius = 6 / globalScale
            const x = node.x - cardW / 2
            const y = node.y - cardH / 2

            // Card shadow
            ctx.shadowColor = 'rgba(0, 0, 0, 0.1)'
            ctx.shadowBlur = 8 / globalScale
            ctx.shadowOffsetY = 2 / globalScale

            // Card background
            ctx.beginPath()
            ctx.roundRect(x, y, cardW, cardH, radius)
            ctx.fillStyle = isSelected ? '#ffffff' : 'rgba(255, 255, 255, 0.95)'
            ctx.fill()

            // Top border (status color)
            ctx.beginPath()
            ctx.moveTo(x + radius, y)
            ctx.lineTo(x + cardW - radius, y)
            ctx.strokeStyle = color
            ctx.lineWidth = 3 / globalScale
            ctx.stroke()

            // Card border
            ctx.beginPath()
            ctx.roundRect(x, y, cardW, cardH, radius)
            ctx.strokeStyle = isSelected ? '#3b82f6' : 'rgba(0, 0, 0, 0.1)'
            ctx.lineWidth = (isSelected ? 2 : 1) / globalScale
            ctx.stroke()

            ctx.shadowColor = 'transparent'
            ctx.shadowBlur = 0

            // Date text
            const dateStr = node._date ? node._date.toLocaleDateString(undefined, {
                month: 'short', day: 'numeric'
            }) : ''
            ctx.font = `500 ${10 / globalScale}px Inter, sans-serif`
            ctx.fillStyle = '#64748b'
            ctx.textAlign = 'left'
            ctx.fillText(dateStr, x + 8 / globalScale, y + 14 / globalScale)

            // Title text
            const title = node.name || node.title || node.id || ''
            const maxChars = Math.floor(cardW * globalScale / 7)
            const displayTitle = title.length > maxChars ? title.substring(0, maxChars - 2) + '...' : title
            ctx.font = `600 ${11 / globalScale}px Inter, sans-serif`
            ctx.fillStyle = '#1e293b'
            ctx.fillText(displayTitle, x + 8 / globalScale, y + 30 / globalScale)

            // Target badge
            if (isTarget) {
                ctx.font = `700 ${9 / globalScale}px Inter, sans-serif`
                ctx.fillStyle = '#f59e0b'
                ctx.textAlign = 'right'
                ctx.fillText('⭐ TARGET', x + cardW - 8 / globalScale, y + 14 / globalScale)
            }
        } else {
            // Dot mode - simple circle
            ctx.beginPath()
            ctx.arc(node.x, node.y, size, 0, 2 * Math.PI)
            ctx.fillStyle = color
            ctx.fill()

            // Border
            ctx.strokeStyle = isTarget ? '#b45309' : 'rgba(255, 255, 255, 0.8)'
            ctx.lineWidth = isTarget ? 2 : 1.5
            ctx.stroke()
        }
    }, [getNodeColor, isNodeVisible, selectedNode, targetEventId])

    // Custom link painting
    const paintLink = useCallback((link, ctx, globalScale) => {
        const start = link.source
        const end = link.target

        // Strict coordinate validation - both nodes must have valid finite coordinates
        if (!start || !end) return
        if (typeof start.x !== 'number' || typeof start.y !== 'number' ||
            typeof end.x !== 'number' || typeof end.y !== 'number') return
        if (!isFinite(start.x) || !isFinite(start.y) ||
            !isFinite(end.x) || !isFinite(end.y)) return

        // Check time filter visibility
        if (!isNodeVisible(start) || !isNodeVisible(end)) return

        // Get current viewport bounds from the graph (with generous margin)
        // This prevents drawing links where nodes are way off-screen
        const graphInstance = graphRef.current
        if (graphInstance) {
            const { x: centerX, y: centerY, k: zoom } = graphInstance.zoom?.() || { x: 0, y: 0, k: 1 }
            const viewWidth = dimensions.width / zoom
            const viewHeight = dimensions.height / zoom
            const margin = 100 / zoom  // Allow some margin for partial visibility

            const bounds = {
                left: centerX - viewWidth / 2 - margin,
                right: centerX + viewWidth / 2 + margin,
                top: centerY - viewHeight / 2 - margin,
                bottom: centerY + viewHeight / 2 + margin
            }

            // Skip if both nodes are on the same side outside bounds
            const startOutLeft = start.x < bounds.left
            const startOutRight = start.x > bounds.right
            const endOutLeft = end.x < bounds.left
            const endOutRight = end.x > bounds.right

            // If source is completely off-screen left/right and target is in view,
            // don't draw the link (it will look like it comes from nowhere)
            if ((startOutLeft && !endOutLeft) || (startOutRight && !endOutRight)) {
                return  // Source off-screen, skip link
            }
        }

        const color = getLinkColor(link)
        const showCard = globalScale >= CARD_MIN_ZOOM

        // Calculate direction
        const dx = end.x - start.x
        const dy = end.y - start.y
        const dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < 20) return

        const angle = Math.atan2(dy, dx)

        // Calculate start and end points at card/node edges
        let startX, startY, endX, endY

        if (showCard) {
            // Card mode: calculate intersection with card rectangle
            const cardW = CARD_WIDTH / globalScale
            const cardH = CARD_HEIGHT / globalScale

            // For start node - find edge intersection
            const startEdge = getRectEdgePoint(start.x, start.y, cardW, cardH, angle)
            startX = startEdge.x
            startY = startEdge.y

            // For end node - find edge intersection (opposite direction)
            const endEdge = getRectEdgePoint(end.x, end.y, cardW, cardH, angle + Math.PI)
            endX = endEdge.x
            endY = endEdge.y
        } else {
            // Dot mode: use circular offset
            const startOffset = NODE_BASE_SIZE + 2
            const endOffset = NODE_BASE_SIZE + 6

            startX = start.x + startOffset * Math.cos(angle)
            startY = start.y + startOffset * Math.sin(angle)
            endX = end.x - endOffset * Math.cos(angle)
            endY = end.y - endOffset * Math.sin(angle)
        }

        // Draw line
        ctx.beginPath()
        ctx.moveTo(startX, startY)
        ctx.lineTo(endX, endY)
        ctx.strokeStyle = color
        ctx.lineWidth = Math.max(1, 1.5 / globalScale)
        ctx.globalAlpha = 0.6
        ctx.stroke()
        ctx.globalAlpha = 1

        // Draw arrow at the end point
        const arrowLen = 6 / globalScale
        ctx.beginPath()
        ctx.moveTo(endX, endY)
        ctx.lineTo(
            endX - arrowLen * Math.cos(angle - Math.PI / 6),
            endY - arrowLen * Math.sin(angle - Math.PI / 6)
        )
        ctx.lineTo(
            endX - arrowLen * Math.cos(angle + Math.PI / 6),
            endY - arrowLen * Math.sin(angle + Math.PI / 6)
        )
        ctx.closePath()
        ctx.fillStyle = color
        ctx.globalAlpha = 0.7
        ctx.fill()
        ctx.globalAlpha = 1
    }, [getLinkColor, isNodeVisible, dimensions])

    // Handle zoom changes for LOD
    const handleZoom = useCallback((transform) => {
        setCurrentZoom(transform.k)
    }, [])

    // Handle node click
    const handleNodeClick = useCallback((node) => {
        if (onNodeClick && isNodeVisible(node)) {
            onNodeClick(node)
        }
    }, [onNodeClick, isNodeVisible])

    // Reset view
    const handleResetView = useCallback(() => {
        if (graphRef.current) {
            graphRef.current.zoomToFit(400, 50)
        }
    }, [])

    // Initial zoom to fit
    useEffect(() => {
        if (graphRef.current && processedData.nodes.length > 0) {
            setTimeout(() => {
                graphRef.current?.zoomToFit(400, 80)
            }, 100)
        }
    }, [processedData.nodes.length])

    return (
        <div className="canvas-timeline-graph" ref={containerRef}>
            <ForceGraph2D
                ref={graphRef}
                width={dimensions.width}
                height={dimensions.height}
                graphData={processedData}
                // Layout forces
                d3AlphaDecay={0.02}
                d3VelocityDecay={0.3}
                cooldownTicks={100}
                // Y-axis collision only (X is fixed)
                d3Force={(forceId) => {
                    if (forceId === 'charge') return null  // No charge repulsion
                    if (forceId === 'link') return d3.forceLink().strength(0.05)  // Weak links
                    if (forceId === 'collide') return d3.forceCollide(60)  // Strong collision
                    if (forceId === 'center') return null  // No centering
                }}
                // Rendering
                nodeCanvasObject={paintNode}
                linkCanvasObject={paintLink}
                nodePointerAreaPaint={(node, color, ctx, globalScale) => {
                    const size = currentZoom >= CARD_MIN_ZOOM
                        ? Math.max(CARD_WIDTH, CARD_HEIGHT) / 2 / globalScale
                        : NODE_BASE_SIZE + 4
                    ctx.beginPath()
                    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI)
                    ctx.fillStyle = color
                    ctx.fill()
                }}
                // Interaction
                onNodeClick={handleNodeClick}
                onZoom={handleZoom}
                enableNodeDrag={false}
                enableZoomInteraction={true}
                enablePanInteraction={true}
                minZoom={0.1}
                maxZoom={5}
            />

            <div className="graph-overlay-controls">
                <button
                    className="control-btn"
                    onClick={handleResetView}
                    title="Reset View"
                >
                    ⟲
                </button>
            </div>

            <GraphLegend />
        </div>
    )
}

export default CanvasTimelineGraph
