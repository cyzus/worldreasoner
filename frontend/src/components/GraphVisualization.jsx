import React, { useRef, useEffect } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import * as d3 from 'd3'
import './GraphVisualization.css'

function GraphVisualization({ graphData, onNodeClick, selectedNode, forceSettings }) {
  const graphRef = useRef()
  const animationFrameRef = useRef()
  const timeRef = useRef(0)
  const previousNodesRef = useRef(new Map())
  const hasZoomedRef = useRef(false) // Track if we've done initial zoom
  const draggedNodeRef = useRef(null) // Track currently dragged node
  const pulseTimeRef = useRef(Date.now()) // Cache time for pulsing animation
  const pulseAnimationRef = useRef(null) // Track pulsing animation frame

  // Preserve node positions when filtering to prevent jarring movements
  useEffect(() => {
    // Restore positions for new nodes from the ref
    if (graphData.nodes.length > 0) {
      graphData.nodes.forEach(node => {
        if (previousNodesRef.current.has(node.id)) {
          const prevNode = previousNodesRef.current.get(node.id)
          // Only restore if valid
          if (Number.isFinite(prevNode.x) && Number.isFinite(prevNode.y)) {
            node.x = prevNode.x
            node.y = prevNode.y
            node.vx = prevNode.vx || 0
            node.vy = prevNode.vy || 0
          }
        }
      })
    }

    // Save positions of the CURRENT nodes when this effect is cleaned up (i.e., before next update)
    return () => {
      graphData.nodes.forEach(node => {
        // Only save if valid coordinates exist
        if (Number.isFinite(node.x) && Number.isFinite(node.y)) {
          previousNodesRef.current.set(node.id, {
            x: node.x,
            y: node.y,
            vx: node.vx,
            vy: node.vy
          })
        }
      })
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
      ?.distanceMax(600) // Increased range for better spacing

    // Center force (keeps the graph centered in the view)
    // We use a standard center force for viewport centering
    fg.d3Force('center', d3.forceCenter(0, 0))

    // Radial gravity (pulls nodes toward center)
    // This is the "Center Gravity" control - using forceRadial for true gravity
    fg.d3Force('gravity', d3.forceRadial(0, 0, 0).strength(forceSettings.centerStrength))

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
    // Use dynamic radius based on node size + padding
    fg.d3Force('collide', d3.forceCollide(node => Math.max(4, (node.size || 1) * 4) + 5).strength(0.7))

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

  // Update pulse time for outcome nodes at reduced frequency (30 fps instead of 60)
  // This prevents calling Date.now() on every paint call
  // OPTIMIZATION: Pause animation when page is hidden to save CPU/GPU
  useEffect(() => {
    const hasOutcomeNode = graphData.nodes.some(node => node.isOutcome)
    if (!hasOutcomeNode) {
      if (pulseAnimationRef.current) {
        cancelAnimationFrame(pulseAnimationRef.current)
        pulseAnimationRef.current = null
      }
      return
    }

    let lastUpdate = 0
    const updateInterval = 1000 / 30 // 30 fps for smooth pulsing

    const updatePulseTime = (timestamp) => {
      // Skip animation if page is hidden (browser tab not active)
      if (document.hidden) {
        pulseAnimationRef.current = requestAnimationFrame(updatePulseTime)
        return
      }

      if (timestamp - lastUpdate >= updateInterval) {
        pulseTimeRef.current = Date.now()
        lastUpdate = timestamp
        // Trigger a single repaint
        if (graphRef.current) {
          graphRef.current.refresh()
        }
      }
      pulseAnimationRef.current = requestAnimationFrame(updatePulseTime)
    }

    pulseAnimationRef.current = requestAnimationFrame(updatePulseTime)

    // Add visibility change listener to handle tab switching
    const handleVisibilityChange = () => {
      if (!document.hidden && hasOutcomeNode) {
        // Resume animation when page becomes visible
        if (!pulseAnimationRef.current) {
          pulseAnimationRef.current = requestAnimationFrame(updatePulseTime)
        }
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      if (pulseAnimationRef.current) {
        cancelAnimationFrame(pulseAnimationRef.current)
        pulseAnimationRef.current = null
      }
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [graphData.nodes])

  // DISABLED: Trigger continuous repainting for pulsing animation on outcome nodes
  // This was causing performance issues by repainting the entire canvas at 60fps
  // TODO: Re-implement with throttling if pulsing animation is needed
  /*
  useEffect(() => {
    const hasOutcomeNode = graphData.nodes.some(node => node.isOutcome)
    if (!hasOutcomeNode) return

    const animate = () => {
      if (graphRef.current) {
        // Force a redraw by slightly updating the graph reference
        // This triggers the canvas to repaint and show the pulsing animation
        graphRef.current.refresh()
      }
      animationFrameRef.current = requestAnimationFrame(animate)
    }

    animationFrameRef.current = requestAnimationFrame(animate)

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current)
      }
    }
  }, [graphData.nodes])
  */


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
    const isOutcome = node.isOutcome

    // Calculate label opacity based on zoom level for smooth fade
    // Labels fully visible at zoom >= 1.0, fade out smoothly as zoom decreases
    const labelOpacity = Math.min(1, Math.max(0, (globalScale - 0.3) / 0.7))

    // Draw pulsing glow for outcome node
    if (isOutcome) {
      const time = pulseTimeRef.current / 1000
      const pulse = 0.7 + Math.sin(time * 2) * 0.3 // Pulsing between 0.4 and 1.0
      ctx.beginPath()
      ctx.arc(node.x, node.y, nodeSize + 12 / globalScale, 0, 2 * Math.PI, false)
      const outcomeGradient = ctx.createRadialGradient(node.x, node.y, nodeSize, node.x, node.y, nodeSize + 12 / globalScale)
      outcomeGradient.addColorStop(0, `rgba(255, 193, 7, ${0.4 * pulse})`) // Gold glow
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
    nodeGradient.addColorStop(0, lightenColor(node.color || '#888', 20))
    nodeGradient.addColorStop(1, node.color || '#888')
    ctx.fillStyle = nodeGradient
    ctx.fill()

    // Add border (gold for outcome, dark for selected, light for others)
    if (isOutcome) {
      ctx.strokeStyle = '#FFC107' // Gold
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
      ctx.strokeStyle = '#FFC107'
      ctx.lineWidth = 2 / globalScale
      ctx.stroke()
    }

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
      const textColor = isOutcome ? '#FFC107' : (isSelected ? '#212529' : '#495057')
      let rgb
      if (textColor === '#FFC107') {
        rgb = [255, 193, 7]
      } else if (textColor === '#212529') {
        rgb = [33, 37, 41]
      } else {
        rgb = [73, 80, 87]
      }
      ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${labelOpacity})`

      // Add "OUTCOME" badge above the label for outcome nodes
      let labelY = node.y + nodeSize + fontSize + 4 / globalScale
      if (isOutcome) {
        const badgeY = node.y + nodeSize + fontSize / 2 + 2 / globalScale
        ctx.font = `700 ${fontSize * 0.7}px Inter, sans-serif`
        ctx.fillStyle = `rgba(255, 193, 7, ${labelOpacity})`
        ctx.fillText('⭐ OUTCOME', node.x, badgeY)
        labelY += fontSize * 0.8
        ctx.font = `600 ${fontSize}px Inter, sans-serif`
      }

      ctx.fillText(label, node.x, labelY)

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

    // Color and style based on edge type
    const isSynthetic = link.isSynthetic || link.type === 'potentially_relevant'
    const alpha = isSynthetic ? 0.4 : Math.min(0.6, Math.max(0.25, link.weight))
    const color = isSynthetic
      ? `rgba(156, 39, 176, ${alpha})`  // Purple for synthetic links
      : `rgba(108, 117, 125, ${alpha})`  // Gray for regular links
    const lineWidth = isSynthetic
      ? 1 / globalScale  // Thinner for synthetic
      : Math.max(1.5, link.weight * 2) / globalScale

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

    // Don't draw if nodes are too close (prevents glitches during initialization)
    if (distance < startNodeSize + endNodeSize + arrowLength) {
      return
    }

    // Don't draw if either node is effectively invisible (e.g. during transitions)
    // This prevents "ghost edges" connecting to nodes that haven't faded in yet
    if (start.opacity === 0 || end.opacity === 0) {
      return
    }

    // Adjust start and end points to account for node size and arrow
    const startX = start.x + (startNodeSize * Math.cos(angle))
    const startY = start.y + (startNodeSize * Math.sin(angle))
    const endX = end.x - ((endNodeSize + arrowLength) * Math.cos(angle))
    const endY = end.y - ((endNodeSize + arrowLength) * Math.sin(angle))

    // Draw main line (dashed for synthetic edges)
    ctx.beginPath()
    ctx.moveTo(startX, startY)
    ctx.lineTo(endX, endY)
    ctx.strokeStyle = color
    ctx.lineWidth = lineWidth

    // Set dash pattern for synthetic edges
    if (isSynthetic) {
      ctx.setLineDash([5 / globalScale, 5 / globalScale])
    } else {
      ctx.setLineDash([])
    }

    ctx.stroke()
    ctx.setLineDash([]) // Reset dash pattern

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
          // Track dragged node without reheating simulation during drag
          // This prevents performance issues from continuous simulation updates
          draggedNodeRef.current = node
        }}
        onNodeDragEnd={(node) => {
          // Release node - let forces take over
          node.fx = undefined
          node.fy = undefined
          draggedNodeRef.current = null

          // Only reheat simulation after drag ends for smooth settling
          if (graphRef.current?.d3ReheatSimulation) {
            graphRef.current.d3ReheatSimulation()
          }
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
        cooldownTicks={50} // Reduced from 200 for faster settling after drag
        warmupTicks={0}
        d3AlphaDecay={0.02} // Increased from 0.01 for faster stopping
        d3VelocityDecay={0.4} // Increased friction for quicker settling
        d3AlphaMin={0.005} // Higher threshold to stop simulation sooner
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
