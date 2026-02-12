/**
 * Shared Graph Rendering Utilities
 * Single source of truth for rendering nodes and links in force graphs
 */
import { GraphStyles } from '../styles/GraphStyles'

// Helper function to lighten colors
export const lightenColor = (color, percent) => {
    const num = parseInt(color.replace("#", ""), 16)
    const amt = Math.round(2.55 * percent)
    const R = (num >> 16) + amt
    const G = (num >> 8 & 0x00FF) + amt
    const B = (num & 0x0000FF) + amt
    return "#" + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
        (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 + (B < 255 ? B < 1 ? 0 : B : 255))
        .toString(16).slice(1)
}

// Helper function to convert hex to rgba
export const hexToRgba = (hex, alpha) => {
    const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex)
    if (result) {
        return `rgba(${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}, ${alpha})`
    }
    return `rgba(108, 117, 125, ${alpha})` // Fallback grey
}

// Helper to check if node should be visible based on time filter
const isNodeVisible = (node, timeFilter) => {
    if (!timeFilter || !timeFilter.start || !timeFilter.end) return true

    // Check for date properties
    const dateStr = node.properties?.occurred_date || node.properties?.predicted_date
    if (!dateStr) return false // Hide nodes without dates when filter is active

    const date = new Date(dateStr)
    return date >= timeFilter.start && date <= timeFilter.end
}

/**
 * Paint a node on the canvas
 * @param {Object} node - Node data
 * @param {CanvasRenderingContext2D} ctx - Canvas context
 * @param {number} globalScale - Current zoom level
 * @param {Object} options - Additional options (selectedNode, pulseTime, timeFilter)
 */
export const paintNode = (node, ctx, globalScale, options = {}) => {
    const { selectedNode, pulseTime, timeFilter } = options

    // Check visibility first
    if (!isNodeVisible(node, timeFilter)) {
        return
    }

    // Check if node has valid coordinates
    if (!node.x || !node.y || !isFinite(node.x) || !isFinite(node.y)) {
        return
    }

    const label = node.name || node.title || node.id
    const fontSize = 11 / globalScale
    const isOutcome = node.isOutcome || node.properties?.is_actual_outcome
    const nodeSize = isOutcome ? GraphStyles.nodeSize.target + 3 : GraphStyles.nodeSize.default + 3
    const isSelected = selectedNode && selectedNode.id === node.id

    // Determine event status
    const eventStatus = node.properties?.status || node.status || 'unknown'
    const isConfirmed = eventStatus === 'occurred'
    const isPredicted = eventStatus === 'predicted' || eventStatus === 'uncertain'

    // Calculate label opacity based on zoom level
    const labelOpacity = Math.min(1, Math.max(0, (globalScale - 0.3) / 0.7))

    // Draw pulsing glow for outcome/target node
    if (isOutcome) {
        const time = (pulseTime || Date.now()) / 1000
        const pulse = 0.7 + Math.sin(time * 2) * 0.3
        ctx.beginPath()
        ctx.arc(node.x, node.y, nodeSize + 12 / globalScale, 0, 2 * Math.PI, false)
        const outcomeGradient = ctx.createRadialGradient(node.x, node.y, nodeSize, node.x, node.y, nodeSize + 12 / globalScale)
        outcomeGradient.addColorStop(0, `rgba(255, 193, 7, ${0.4 * pulse})`)
        outcomeGradient.addColorStop(1, 'rgba(255, 193, 7, 0)')
        ctx.fillStyle = outcomeGradient
        ctx.fill()
    }

    // Draw glow for selected node
    if (isSelected) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, nodeSize + 8 / globalScale, 0, 2 * Math.PI, false)
        const gradient = ctx.createRadialGradient(node.x, node.y, nodeSize, node.x, node.y, nodeSize + 8 / globalScale)
        gradient.addColorStop(0, 'rgba(33, 37, 41, 0.25)')
        gradient.addColorStop(1, 'rgba(33, 37, 41, 0)')
        ctx.fillStyle = gradient
        ctx.fill()
    }

    // Draw node circle with gradient
    ctx.beginPath()
    ctx.arc(node.x, node.y, nodeSize, 0, 2 * Math.PI, false)

    const nodeGradient = ctx.createRadialGradient(
        node.x - nodeSize / 3, node.y - nodeSize / 3, 0,
        node.x, node.y, nodeSize
    )

    // Choose color based on event status (single source of truth)
    let baseColor
    if (isOutcome) {
        // Target event - gold
        baseColor = GraphStyles.nodeColors.target
    } else if (isConfirmed) {
        // Confirmed events - green (with time-based variation)
        const dateStr = node.properties?.occurred_date || node.occurred_date
        if (dateStr) {
            const eventDate = new Date(dateStr)
            const now = new Date()
            const ageInDays = (now - eventDate) / (1000 * 60 * 60 * 24)

            // Older events = darker green, newer = lighter green
            if (ageInDays > 180) {
                baseColor = '#065f46' // Very dark green (old)
            } else if (ageInDays > 90) {
                baseColor = '#047857' // Dark green
            } else if (ageInDays > 30) {
                baseColor = '#059669' // Medium green
            } else if (ageInDays > 7) {
                baseColor = '#10b981' // Bright green
            } else {
                baseColor = '#34d399' // Light green (recent)
            }
        } else {
            baseColor = '#10b981' // Default bright green
        }
    } else if (isPredicted) {
        // Predicted events - blue/gray gradient
        const dateStr = node.properties?.predicted_date || node.predicted_date
        if (dateStr) {
            const predictedDate = new Date(dateStr)
            const now = new Date()
            const daysUntil = (predictedDate - now) / (1000 * 60 * 60 * 24)

            // Soon = darker blue, far future = lighter blue/gray
            if (daysUntil < 7) {
                baseColor = '#1e40af' // Dark blue (imminent)
            } else if (daysUntil < 30) {
                baseColor = '#3b82f6' // Medium blue
            } else if (daysUntil < 90) {
                baseColor = '#60a5fa' // Light blue
            } else {
                baseColor = '#93c5fd' // Very light blue (distant)
            }
        } else {
            baseColor = '#6b7280' // Gray (no date)
        }
    } else {
        // Unknown status - use domain color as fallback
        baseColor = GraphStyles.nodeColors[node.domain] || node.color || GraphStyles.nodeColors.general
    }

    nodeGradient.addColorStop(0, lightenColor(baseColor, 20))
    nodeGradient.addColorStop(1, baseColor)
    ctx.fillStyle = nodeGradient
    ctx.fill()

    // Add border
    if (isOutcome) {
        ctx.strokeStyle = GraphStyles.nodeColors.target
        ctx.lineWidth = 3 / globalScale
    } else if (isSelected) {
        ctx.strokeStyle = '#212529'
        ctx.lineWidth = 3 / globalScale
    } else {
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.2)'
        ctx.lineWidth = 1.5 / globalScale
    }
    ctx.stroke()

    // Add outer ring for outcome node
    if (isOutcome) {
        ctx.beginPath()
        ctx.arc(node.x, node.y, nodeSize + 4 / globalScale, 0, 2 * Math.PI, false)
        ctx.strokeStyle = GraphStyles.nodeColors.target
        ctx.lineWidth = 2 / globalScale
        ctx.stroke()
    }

    // Draw label
    if (labelOpacity > 0.05) {
        ctx.font = `600 ${fontSize}px Inter, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'

        ctx.shadowColor = `rgba(255, 255, 255, ${0.8 * labelOpacity})`
        ctx.shadowBlur = 3
        ctx.shadowOffsetY = 0

        const textColor = isOutcome ? GraphStyles.nodeColors.target : (isSelected ? '#212529' : '#495057')
        let rgb
        if (textColor === GraphStyles.nodeColors.target) {
            rgb = [255, 215, 0]
        } else if (textColor === '#212529') {
            rgb = [33, 37, 41]
        } else {
            rgb = [73, 80, 87]
        }
        ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${labelOpacity})`

        let labelY = node.y + nodeSize + fontSize + 4 / globalScale
        if (isOutcome) {
            const badgeY = node.y + nodeSize + fontSize / 2 + 2 / globalScale
            ctx.font = `700 ${fontSize * 0.7}px Inter, sans-serif`
            ctx.fillStyle = `rgba(255, 193, 7, ${labelOpacity})`
            ctx.fillText('⭐ TARGET', node.x, badgeY)
            labelY += fontSize * 0.8
            ctx.font = `600 ${fontSize}px Inter, sans-serif`
            ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${labelOpacity})`
        }

        const displayLabel = label.length > 25 ? label.substring(0, 25) + '...' : label
        ctx.fillText(displayLabel, node.x, labelY)

        ctx.shadowColor = 'transparent'
        ctx.shadowBlur = 0
        ctx.shadowOffsetY = 0
    }
}

/**
 * Paint a link on the canvas
 * @param {Object} link - Link data
 * @param {CanvasRenderingContext2D} ctx - Canvas context
 * @param {number} globalScale - Current zoom level
 * @param {Object} options - Additional options (timeFilter)
 */
export const paintLink = (link, ctx, globalScale, options = {}) => {
    const { timeFilter } = options
    const start = link.source
    const end = link.target

    // Check visibility first - both nodes must be visible
    if (!isNodeVisible(start, timeFilter) || !isNodeVisible(end, timeFilter)) {
        return
    }

    if (!start.x || !start.y || !end.x || !end.y ||
        !isFinite(start.x) || !isFinite(start.y) || !isFinite(end.x) || !isFinite(end.y)) {
        return
    }

    // Check if this is an impact edge
    const isImpact = link.edge_type?.startsWith('impact_') || link.type?.startsWith('impact_')
    const edgeType = link.edge_type || link.type

    const isSynthetic = link.isSynthetic || link.type === 'potentially_relevant'

    // For impact edges, use impact_magnitude for alpha and width
    let alpha, lineWidth
    if (isImpact) {
        const magnitude = link.properties?.impact_magnitude || link.weight || 0.5
        alpha = magnitude
        lineWidth = Math.max(2, magnitude * 3.5) / globalScale
    } else {
        alpha = isSynthetic ? 0.4 : Math.min(0.7, Math.max(0.4, link.weight || link.strength || 0.5))
        lineWidth = isSynthetic
            ? 1 / globalScale
            : Math.max(1.5, (link.weight || link.strength || 1) * 2.5) / globalScale
    }

    const baseColor = GraphStyles.linkColors[edgeType] || GraphStyles.linkColors[link.relation_type] || GraphStyles.linkColors.default || '#6c757d'
    const color = isSynthetic
        ? `rgba(156, 39, 176, ${alpha})`
        : hexToRgba(baseColor, alpha)

    const dx = end.x - start.x
    const dy = end.y - start.y
    const angle = Math.atan2(dy, dx)
    const distance = Math.sqrt(dx * dx + dy * dy)

    const startNodeSize = GraphStyles.nodeSize.default + 3
    const endNodeSize = GraphStyles.nodeSize.default + 3

    const clampedScale = Math.max(0.3, Math.min(0.8, globalScale))
    const arrowLength = 10 * clampedScale
    const arrowWidth = 6 * clampedScale

    if (distance < startNodeSize + endNodeSize + arrowLength) {
        return
    }

    const startX = start.x + (startNodeSize * Math.cos(angle))
    const startY = start.y + (startNodeSize * Math.sin(angle))
    const endX = end.x - ((endNodeSize + arrowLength) * Math.cos(angle))
    const endY = end.y - ((endNodeSize + arrowLength) * Math.sin(angle))

    ctx.beginPath()
    ctx.moveTo(startX, startY)
    ctx.lineTo(endX, endY)
    ctx.strokeStyle = color
    ctx.lineWidth = lineWidth

    // Impact edges use dashed lines, synthetic edges also use dashes
    if (isImpact) {
        ctx.setLineDash([8 / globalScale, 4 / globalScale])
    } else if (isSynthetic) {
        ctx.setLineDash([5 / globalScale, 5 / globalScale])
    } else {
        ctx.setLineDash([])
    }

    ctx.stroke()
    ctx.setLineDash([])

    // Draw arrow
    const arrowX = end.x - (endNodeSize * Math.cos(angle))
    const arrowY = end.y - (endNodeSize * Math.sin(angle))

    ctx.beginPath()
    ctx.moveTo(arrowX, arrowY)
    ctx.lineTo(
        arrowX - arrowLength * Math.cos(angle - Math.PI / 6),
        arrowY - arrowLength * Math.sin(angle - Math.PI / 6)
    )
    ctx.lineTo(
        arrowX - arrowLength * Math.cos(angle + Math.PI / 6),
        arrowY - arrowLength * Math.sin(angle + Math.PI / 6)
    )
    ctx.closePath()
    ctx.fillStyle = color
    ctx.fill()
}

/**
 * Render the legend overlay component
 */
export const GraphLegend = () => (
    <div style={{
        position: 'absolute',
        top: 10,
        left: 10,
        zIndex: 10,
        background: 'rgba(255,255,255,0.95)',
        padding: '10px 14px',
        borderRadius: '8px',
        fontSize: '11px',
        boxShadow: '0 2px 12px rgba(0,0,0,0.15)',
        pointerEvents: 'none',
        maxWidth: '200px'
    }}>
        {/* Node colors section */}
        <div style={{ marginBottom: '10px' }}>
            <div style={{ fontWeight: '600', marginBottom: '6px', fontSize: '12px', color: '#374151' }}>
                Event Impact & Status
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{
                    width: 12,
                    height: 12,
                    borderRadius: '50%',
                    backgroundColor: GraphStyles.linkColors.impact_positive,
                    display: 'inline-block',
                    marginRight: 6,
                    border: '1px solid rgba(0,0,0,0.1)'
                }}></span>
                <span style={{ fontSize: '10px' }}>Positive Impact</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{
                    width: 12,
                    height: 12,
                    borderRadius: '50%',
                    backgroundColor: GraphStyles.linkColors.impact_negative,
                    display: 'inline-block',
                    marginRight: 6,
                    border: '1px solid rgba(0,0,0,0.1)'
                }}></span>
                <span style={{ fontSize: '10px' }}>Negative Impact</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{
                    width: 12,
                    height: 12,
                    borderRadius: '50%',
                    backgroundColor: GraphStyles.linkColors.impact_mixed,
                    display: 'inline-block',
                    marginRight: 6,
                    border: '1px solid rgba(0,0,0,0.1)'
                }}></span>
                <span style={{ fontSize: '10px' }}>Mixed Impact</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{
                    width: 12,
                    height: 12,
                    borderRadius: '50%',
                    backgroundColor: GraphStyles.nodeColors.target,
                    display: 'inline-block',
                    marginRight: 6,
                    border: '2px solid #f59e0b'
                }}></span>
                <span style={{ fontSize: '10px', fontWeight: '600' }}>Target / Outcome</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center' }}>
                <span style={{
                    width: 12,
                    height: 12,
                    borderRadius: '50%',
                    background: 'linear-gradient(135deg, #93c5fd 0%, #3b82f6 100%)',
                    display: 'inline-block',
                    marginRight: 6,
                    border: '1px solid rgba(0,0,0,0.1)'
                }}></span>
                <span style={{ fontSize: '10px' }}>No Impact (Neutral)</span>
            </div>
        </div>

        {/* Causal relations section */}
        <div style={{ borderTop: '1px solid #e5e7eb', paddingTop: '8px' }}>
            <div style={{ fontWeight: '600', marginBottom: '6px', fontSize: '12px', color: '#374151' }}>
                Causal Relations
            </div>

            {/* Positive relations */}
            <div style={{ marginBottom: '6px' }}>
                <div style={{ fontSize: '10px', fontWeight: '600', color: '#059669', marginBottom: '3px' }}>Toward Target</div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px', marginLeft: '8px' }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.amplifies, display: 'inline-block', marginRight: 6 }}></span>
                    <span style={{ fontSize: '10px' }}>Amplifies</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px', marginLeft: '8px' }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.triggers, display: 'inline-block', marginRight: 6 }}></span>
                    <span style={{ fontSize: '10px' }}>Triggers</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px', marginLeft: '8px' }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.enables, display: 'inline-block', marginRight: 6 }}></span>
                    <span style={{ fontSize: '10px' }}>Enables</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', marginLeft: '8px' }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.causes, display: 'inline-block', marginRight: 6 }}></span>
                    <span style={{ fontSize: '10px' }}>Causes</span>
                </div>
            </div>

            {/* Negative relations */}
            <div style={{ marginBottom: '6px' }}>
                <div style={{ fontSize: '10px', fontWeight: '600', color: '#dc2626', marginBottom: '3px' }}>Away from Target</div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px', marginLeft: '8px' }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.prevents, display: 'inline-block', marginRight: 6 }}></span>
                    <span style={{ fontSize: '10px' }}>Prevents</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', marginLeft: '8px' }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.inhibits, display: 'inline-block', marginRight: 6 }}></span>
                    <span style={{ fontSize: '10px' }}>Inhibits</span>
                </div>
            </div>

            {/* Neutral relations */}
            <div>
                <div style={{ fontSize: '10px', fontWeight: '600', color: '#6b7280', marginBottom: '3px' }}>Other</div>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: '2px', marginLeft: '8px' }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.correlates, display: 'inline-block', marginRight: 6 }}></span>
                    <span style={{ fontSize: '10px' }}>Correlates</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', marginLeft: '8px' }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.conditional, display: 'inline-block', marginRight: 6 }}></span>
                    <span style={{ fontSize: '10px' }}>Conditional</span>
                </div>
            </div>
        </div>

        {/* Impact relations section */}
        <div style={{ borderTop: '1px solid #e5e7eb', paddingTop: '8px', marginTop: '8px' }}>
            <div style={{ fontWeight: '600', marginBottom: '6px', fontSize: '12px', color: '#374151' }}>
                Outcome Impacts
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '3px' }}>
                <svg width="24" height="2" style={{ marginRight: 6 }}>
                    <line x1="0" y1="1" x2="24" y2="1" stroke={GraphStyles.linkColors.impact_positive} strokeWidth="2" strokeDasharray="4,2" />
                </svg>
                <span style={{ fontSize: '10px' }}>Positive Impact</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '3px' }}>
                <svg width="24" height="2" style={{ marginRight: 6 }}>
                    <line x1="0" y1="1" x2="24" y2="1" stroke={GraphStyles.linkColors.impact_negative} strokeWidth="2" strokeDasharray="4,2" />
                </svg>
                <span style={{ fontSize: '10px' }}>Negative Impact</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '3px' }}>
                <svg width="24" height="2" style={{ marginRight: 6 }}>
                    <line x1="0" y1="1" x2="24" y2="1" stroke={GraphStyles.linkColors.impact_mixed} strokeWidth="2" strokeDasharray="4,2" />
                </svg>
                <span style={{ fontSize: '10px' }}>Mixed Impact</span>
            </div>
            <div style={{ fontSize: '9px', color: '#9ca3af', marginTop: '4px', fontStyle: 'italic' }}>
                Dashed = Impact, Solid = Causal
            </div>
        </div>
    </div>
)
