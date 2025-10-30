import React, { useRef, useEffect } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import './GraphVisualization.css'

const GraphVisualization = ({ graphData, onNodeClick, selectedNode }) => {
  const graphRef = useRef()
  const animationFrameRef = useRef()
  const timeRef = useRef(0)

  // Debug log
  useEffect(() => {
    console.log('GraphVisualization received data:', graphData)
  }, [graphData])

  // Auto-fit graph on load
  useEffect(() => {
    if (graphRef.current && graphData.nodes.length > 0) {
      graphRef.current.zoomToFit(400, 50)
    }
  }, [graphData])

  // Add boundary force to keep nodes contained
  useEffect(() => {
    if (!graphRef.current) return

    const fg = graphRef.current

    // Calculate dynamic boundary size based on number of nodes
    // More nodes = larger boundary to prevent overcrowding
    const nodeCount = graphData.nodes.length
    const baseRadius = 200
    const radiusPerNode = 15 // Each node adds ~15 pixels to radius
    const maxRadius = 800 // Cap at 800 pixels
    const minRadius = 150 // Minimum 150 pixels even for small graphs

    const dynamicRadius = Math.min(
      maxRadius,
      Math.max(minRadius, baseRadius + Math.sqrt(nodeCount) * radiusPerNode)
    )

    // Add bounding box force to contain nodes within dynamic radius
    fg.d3Force('boundary', () => {
      graphData.nodes.forEach(node => {
        if (!node.fx && !node.fy) { // Don't affect pinned/dragged nodes
          const x = node.x || 0
          const y = node.y || 0
          const distance = Math.sqrt(x * x + y * y)

          if (distance > dynamicRadius) {
            // Push node back toward center with force proportional to distance
            const force = (distance - dynamicRadius) * 0.1
            const angle = Math.atan2(y, x)
            node.vx = (node.vx || 0) - Math.cos(angle) * force
            node.vy = (node.vy || 0) - Math.sin(angle) * force
          }
        }
      })
    })
  }, [graphData])


  // Node canvas rendering with glow effect
  const paintNode = (node, ctx, globalScale) => {
    // Check if node has valid coordinates
    if (!node.x || !node.y || !isFinite(node.x) || !isFinite(node.y)) {
      return
    }

    const label = node.name
    const fontSize = 11 / globalScale
    const nodeSize = Math.max(4, node.size * 4)
    const isSelected = selectedNode && selectedNode.id === node.id

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
    nodeGradient.addColorStop(0, lightenColor(node.color || '#888', 20))
    nodeGradient.addColorStop(1, node.color || '#888')
    ctx.fillStyle = nodeGradient
    ctx.fill()

    // Add border
    ctx.strokeStyle = isSelected ? '#212529' : 'rgba(0, 0, 0, 0.2)'
    ctx.lineWidth = (isSelected ? 3 : 1.5) / globalScale
    ctx.stroke()

    // Draw label with shadow
    ctx.font = `600 ${fontSize}px Inter, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'

    // Text shadow for readability
    ctx.shadowColor = 'rgba(255, 255, 255, 0.8)'
    ctx.shadowBlur = 3
    ctx.shadowOffsetY = 0

    ctx.fillStyle = isSelected ? '#212529' : '#495057'
    ctx.fillText(label, node.x, node.y + nodeSize + fontSize + 4 / globalScale)

    // Reset shadow
    ctx.shadowColor = 'transparent'
    ctx.shadowBlur = 0
    ctx.shadowOffsetY = 0
  }

  // Helper function to lighten colors
  const lightenColor = (color, percent) => {
    const num = parseInt(color.replace("#",""), 16)
    const amt = Math.round(2.55 * percent)
    const R = (num >> 16) + amt
    const G = (num >> 8 & 0x00FF) + amt
    const B = (num & 0x0000FF) + amt
    return "#" + (0x1000000 + (R<255?R<1?0:R:255)*0x10000 +
      (G<255?G<1?0:G:255)*0x100 + (B<255?B<1?0:B:255))
      .toString(16).slice(1)
  }

  // Link canvas rendering
  const paintLink = (link, ctx, globalScale) => {
    const start = link.source
    const end = link.target

    // Check if nodes have valid coordinates
    if (!start.x || !start.y || !end.x || !end.y ||
        !isFinite(start.x) || !isFinite(start.y) || !isFinite(end.x) || !isFinite(end.y)) {
      return
    }

    // Color based on edge weight/strength
    const alpha = Math.min(0.6, Math.max(0.25, link.weight))
    const color = `rgba(108, 117, 125, ${alpha})`
    const lineWidth = Math.max(1.5, link.weight * 2) / globalScale

    // Calculate the angle and distance
    const dx = end.x - start.x
    const dy = end.y - start.y
    const angle = Math.atan2(dy, dx)
    const distance = Math.sqrt(dx * dx + dy * dy)

    // Calculate node radii to stop line at node edge
    const startNodeSize = Math.max(4, (start.size || 1) * 4)
    const endNodeSize = Math.max(4, (end.size || 1) * 4)

    // Arrow dimensions (larger for visibility)
    const arrowLength = 12 / globalScale
    const arrowWidth = 8 / globalScale

    // Adjust start and end points to account for node size and arrow
    const startX = start.x + (startNodeSize * Math.cos(angle))
    const startY = start.y + (startNodeSize * Math.sin(angle))
    const endX = end.x - ((endNodeSize + arrowLength) * Math.cos(angle))
    const endY = end.y - ((endNodeSize + arrowLength) * Math.sin(angle))

    // Draw main line
    ctx.beginPath()
    ctx.moveTo(startX, startY)
    ctx.lineTo(endX, endY)
    ctx.strokeStyle = color
    ctx.lineWidth = lineWidth
    ctx.stroke()

    // Draw arrowhead at the adjusted end position
    const arrowTipX = end.x - (endNodeSize * Math.cos(angle))
    const arrowTipY = end.y - (endNodeSize * Math.sin(angle))

    ctx.save()
    ctx.translate(arrowTipX, arrowTipY)
    ctx.rotate(angle)
    ctx.beginPath()
    ctx.moveTo(0, 0)
    ctx.lineTo(-arrowLength, arrowWidth / 2)
    ctx.lineTo(-arrowLength, -arrowWidth / 2)
    ctx.closePath()
    ctx.fillStyle = color
    ctx.fill()
    ctx.restore()
  }

  return (
    <div className="graph-visualization">
      <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        nodeLabel={(node) => node.name}
        nodeCanvasObject={paintNode}
        nodeCanvasObjectMode={() => 'replace'}
        linkCanvasObject={paintLink}
        linkCanvasObjectMode={() => 'replace'}
        onNodeClick={(node) => onNodeClick(node)}
        onNodeDrag={(node) => {
          // Fix node position while dragging
          node.fx = node.x
          node.fy = node.y
        }}
        onNodeDragEnd={(node) => {
          // Release node after dragging
          node.fx = undefined
          node.fy = undefined
        }}
        backgroundColor="#ffffff"
        linkDirectionalArrowLength={0} // We draw custom arrows
        linkDirectionalArrowRelPos={1}
        cooldownTicks={100}
        onEngineStop={() => graphRef.current?.zoomToFit(400, 50)}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        enablePanInteraction={true}
      />
    </div>
  )
}

export default GraphVisualization
