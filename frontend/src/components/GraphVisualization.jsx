import React, { useRef, useEffect, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import ForceControls from './ForceControls'
import './GraphVisualization.css'

const GraphVisualization = ({ graphData, onNodeClick, selectedNode }) => {
  const graphRef = useRef()
  const animationFrameRef = useRef()
  const timeRef = useRef(0)
  const previousNodesRef = useRef(new Map())
  const hasZoomedRef = useRef(false) // Track if we've done initial zoom
  const draggedNodeRef = useRef(null) // Track currently dragged node

  // D3 force controls (Obsidian-style adjustable)
  const [forceSettings, setForceSettings] = useState({
    linkDistance: 40,        // Shorter distance = tighter layout (was 70)
    linkStrength: 1,         // Normal spring strength
    chargeStrength: -150,    // Less repulsion = closer nodes (was -200)
    centerStrength: 0.05     // Very gentle center force (like in examples)
  })


  // Preserve node positions when filtering to prevent jarring movements
  useEffect(() => {
    if (graphData.nodes.length > 0) {
      // Save positions of current nodes
      graphData.nodes.forEach(node => {
        if (previousNodesRef.current.has(node.id)) {
          // Restore previous position if this node existed before
          const prevNode = previousNodesRef.current.get(node.id)
          node.x = prevNode.x
          node.y = prevNode.y
          node.vx = prevNode.vx || 0
          node.vy = prevNode.vy || 0
        }
        // IMPORTANT: Never save or restore fx/fy - they should only be set during active drag
        // Update the map with current position (only x, y, vx, vy - NOT fx/fy)
        previousNodesRef.current.set(node.id, {
          x: node.x,
          y: node.y,
          vx: node.vx,
          vy: node.vy
        })
      })

      // Clean up nodes that no longer exist
      const currentIds = new Set(graphData.nodes.map(n => n.id))
      for (const [id, _] of previousNodesRef.current) {
        if (!currentIds.has(id)) {
          previousNodesRef.current.delete(id)
        }
      }
    }
  }, [graphData])

  // Initial zoom to fit when data first loads
  useEffect(() => {
    if (graphRef.current && graphData.nodes.length > 0 && !hasZoomedRef.current) {
      // Delay to let nodes initialize positions
      const timer = setTimeout(() => {
        if (graphRef.current) {
          graphRef.current.zoomToFit(400, 80)
          hasZoomedRef.current = true
        }
      }, 800) // Wait for initial layout

      return () => clearTimeout(timer)
    }
  }, [graphData.nodes.length]) // Only when node count changes


  // Configure Obsidian-style forces and keep simulation running
  useEffect(() => {
    if (!graphRef.current) return

    const fg = graphRef.current

    // Link force (spring-like attraction between connected nodes)
    fg.d3Force('link')
      ?.distance(forceSettings.linkDistance)
      ?.strength(forceSettings.linkStrength)

    // Charge force (electrostatic repulsion between all nodes)
    fg.d3Force('charge')
      ?.strength(forceSettings.chargeStrength)
      ?.distanceMax(400) // Limit repulsion range

    // Center force (strong pull toward center to prevent boundary clustering)
    if (!fg.d3Force('center')) {
      fg.d3Force('center', window.d3?.forceCenter?.(0, 0))
    }
    fg.d3Force('center')
      ?.x(0)
      ?.y(0)
      ?.strength(forceSettings.centerStrength)

    // Wake up simulation to apply new force settings
    if (fg.d3ReheatSimulation) {
      fg.d3ReheatSimulation()
    }

    // Calculate dynamic boundary size based on number of nodes
    // More compact formula to reduce sparseness
    const nodeCount = graphData.nodes.length
    const baseRadius = 150       // Smaller base (was 200)
    const radiusPerNode = 8       // Less growth per node (was 15)
    const maxRadius = 500         // Smaller max (was 800)
    const minRadius = 120         // Smaller min (was 150)

    const dynamicRadius = Math.min(
      maxRadius,
      Math.max(minRadius, baseRadius + Math.sqrt(nodeCount) * radiusPerNode)
    )

    // Add collision force to prevent overlap (D3 best practice)
    fg.d3Force('collide', window.d3?.forceCollide?.(12)) // Smaller radius for tighter layout (was 15)

    // Add very gentle containment force with buffer zone
    fg.d3Force('contain', () => {
      const bufferZone = 50 // Only start applying force 50px beyond radius

      graphData.nodes.forEach(node => {
        if (!node.fx && !node.fy) {
          const x = node.x || 0
          const y = node.y || 0
          const distance = Math.sqrt(x * x + y * y)

          // Only apply force if node is well beyond the safe radius (buffer zone)
          const threshold = dynamicRadius + bufferZone
          if (distance > threshold) {
            // Very gentle force toward center - much weaker to prevent oscillation
            // Strength increases gradually with distance
            const overshoot = distance - threshold
            const strength = Math.min(overshoot / distance * 0.01, 0.5) // Cap maximum force
            node.vx = (node.vx || 0) - x * strength
            node.vy = (node.vy || 0) - y * strength
          }
        }
      })
    })

  }, [graphData, forceSettings])


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

    // Calculate label opacity based on zoom level for smooth fade
    // Labels fully visible at zoom >= 1.0, fade out smoothly as zoom decreases
    const labelOpacity = Math.min(1, Math.max(0, (globalScale - 0.3) / 0.7))

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

    // Only draw label if opacity is significant (performance optimization)
    if (labelOpacity > 0.05) {
      ctx.font = `600 ${fontSize}px Inter, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'

      // Text shadow for readability, also fades with label
      ctx.shadowColor = `rgba(255, 255, 255, ${0.8 * labelOpacity})`
      ctx.shadowBlur = 3
      ctx.shadowOffsetY = 0

      // Apply opacity to text color
      const textColor = isSelected ? '#212529' : '#495057'
      const rgb = textColor === '#212529'
        ? [33, 37, 41]
        : [73, 80, 87]
      ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${labelOpacity})`
      ctx.fillText(label, node.x, node.y + nodeSize + fontSize + 4 / globalScale)

      // Reset shadow
      ctx.shadowColor = 'transparent'
      ctx.shadowBlur = 0
      ctx.shadowOffsetY = 0
    }
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

    // Arrow dimensions - scale with zoom but clamp to reasonable range
    // Clamp globalScale between 0.3 and 0.8 to keep arrows small
    const clampedScale = Math.max(0.3, Math.min(0.8, globalScale))
    const arrowLength = 10 * clampedScale
    const arrowWidth = 6 * clampedScale

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
      <ForceControls
        forceSettings={forceSettings}
        onForceChange={setForceSettings}
      />
      <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        nodeId="id" // CRITICAL: Stable node identity prevents simulation restart
        linkSource="source"
        linkTarget="target"
        nodeLabel={(node) => node.name}
        nodeCanvasObject={paintNode}
        nodeCanvasObjectMode={() => 'replace'}
        linkCanvasObject={paintLink}
        linkCanvasObjectMode={() => 'replace'}
        onNodeClick={(node, event) => {
          // Single-click for details
          onNodeClick(node)
        }}
        onNodeDrag={(node) => {
          // Wake up simulation gently only when drag starts (not on every drag event)
          if (!draggedNodeRef.current && graphRef.current?.d3ReheatSimulation) {
            // Restart simulation at low energy for forces to apply
            graphRef.current.d3ReheatSimulation()
          }
          draggedNodeRef.current = node
        }}
        onNodeDragEnd={(node) => {
          // Release node - let forces take over
          node.fx = undefined
          node.fy = undefined
          draggedNodeRef.current = null
        }}
        onBackgroundClick={() => {
          // If there was a dragged node that didn't get released, release it now
          if (draggedNodeRef.current) {
            delete draggedNodeRef.current.fx
            delete draggedNodeRef.current.fy
            draggedNodeRef.current = null
          }
        }}
        backgroundColor="#ffffff"
        linkDirectionalArrowLength={0} // We draw custom arrows
        linkDirectionalArrowRelPos={1}
        cooldownTicks={200}
        warmupTicks={0}
        d3AlphaDecay={0.04}
        d3VelocityDecay={0.8}
        d3AlphaMin={0.001}
        onEngineStop={() => {
          // Let simulation rest when not interacting
        }}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        enablePanInteraction={true}
        minZoom={0.1}  // Allow zooming out to see full graph
        maxZoom={8}    // Allow zooming in for details
      />
    </div>
  )
}

export default GraphVisualization
