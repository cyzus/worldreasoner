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

/**
 * Paint a node on the canvas
 * @param {Object} node - Node data
 * @param {CanvasRenderingContext2D} ctx - Canvas context
 * @param {number} globalScale - Current zoom level
 * @param {Object} options - Additional options (selectedNode, targetEventId, pulseTime)
 */
export const paintNode = (node, ctx, globalScale, options = {}) => {
    const { selectedNode, targetEventId, pulseTime } = options

    // Check if node has valid coordinates
    if (!node.x || !node.y || !isFinite(node.x) || !isFinite(node.y)) {
        return
    }

    const label = node.name || node.title || node.id
    const fontSize = 11 / globalScale
    const isTarget = node.id === targetEventId
    const isOutcome = node.isOutcome || isTarget
    const nodeSize = isOutcome ? GraphStyles.nodeSize.target + 3 : GraphStyles.nodeSize.default + 3
    const isSelected = selectedNode && selectedNode.id === node.id

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

    // Use GraphStyles for color
    const baseColor = GraphStyles.nodeColors[node.domain] || node.color || GraphStyles.nodeColors.general

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
 */
export const paintLink = (link, ctx, globalScale) => {
    const start = link.source
    const end = link.target

    if (!start.x || !start.y || !end.x || !end.y ||
        !isFinite(start.x) || !isFinite(start.y) || !isFinite(end.x) || !isFinite(end.y)) {
        return
    }

    const isSynthetic = link.isSynthetic || link.type === 'potentially_relevant'
    const alpha = isSynthetic ? 0.4 : Math.min(0.7, Math.max(0.4, link.weight || link.strength || 0.5))

    const baseColor = GraphStyles.linkColors[link.type] || GraphStyles.linkColors[link.relation_type] || GraphStyles.linkColors.default || '#6c757d'
    const color = isSynthetic
        ? `rgba(156, 39, 176, ${alpha})`
        : hexToRgba(baseColor, alpha)
    const lineWidth = isSynthetic
        ? 1 / globalScale
        : Math.max(1.5, (link.weight || link.strength || 1) * 2.5) / globalScale

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

    if (isSynthetic) {
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
        background: 'rgba(255,255,255,0.9)',
        padding: '8px 12px',
        borderRadius: '6px',
        fontSize: '11px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
        pointerEvents: 'none'
    }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.causes, display: 'inline-block', marginRight: 6 }}></span>
            <span>Causes</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.enables, display: 'inline-block', marginRight: 6 }}></span>
            <span>Enables</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.prevents, display: 'inline-block', marginRight: 6 }}></span>
            <span>Prevents</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '4px' }}>
            <span style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.correlates_with, display: 'inline-block', marginRight: 6 }}></span>
            <span>Correlates</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center' }}>
            <span style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: GraphStyles.linkColors.conditional, display: 'inline-block', marginRight: 6 }}></span>
            <span>Conditional</span>
        </div>
    </div>
)
