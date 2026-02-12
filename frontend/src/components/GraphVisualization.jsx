import React, { useRef, useEffect } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import * as d3 from 'd3'
import './GraphVisualization.css'
import { GraphStyles } from '../styles/GraphStyles'
import { paintNode as sharedPaintNode, paintLink as sharedPaintLink, GraphLegend } from '../utils/graphRendering.jsx'


function GraphVisualization({ graphData, onNodeClick, selectedNode, forceSettings, timeFilter }) {
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

  const containerRef = useRef()
  const [dimensions, setDimensions] = React.useState({ width: 0, height: 0 })

  // Monitor container size
  useEffect(() => {
    if (!containerRef.current) return

    const updateDimensions = () => {
      if (containerRef.current) {
        setDimensions({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight
        })
      }
    }

    // Initial measure
    updateDimensions()

    const resizeObserver = new ResizeObserver(() => {
      updateDimensions()
    })

    resizeObserver.observe(containerRef.current)

    return () => resizeObserver.disconnect()
  }, [])


  // Center on target event or fit to viewport
  useEffect(() => {
    // Only attempt if we have data and dimensions
    if (!graphRef.current || graphData.nodes.length === 0 || dimensions.width === 0) return

    // Reset zoom state when data changes to allow re-centering
    hasZoomedRef.current = false

    let attemptCount = 0
    const maxAttempts = 10

    const attemptCenter = () => {
      if (!graphRef.current) return

      attemptCount++
      const nodes = graphData.nodes

      // Check if nodes have positions from force simulation
      const hasPositions = nodes.some(n => Number.isFinite(n.x) && Number.isFinite(n.y))

      if (!hasPositions && attemptCount < maxAttempts) {
        // Retry after a short delay to let force simulation run
        setTimeout(attemptCenter, 200)
        return
      }

      // Center on actual outcome node if present
      const actualOutcomeNode = nodes.find(n => n.properties?.is_actual_outcome)
      if (actualOutcomeNode && Number.isFinite(actualOutcomeNode.x) && Number.isFinite(actualOutcomeNode.y)) {
        graphRef.current.centerAt(actualOutcomeNode.x, actualOutcomeNode.y, 1000)
        graphRef.current.zoom(1.8, 1000)
        hasZoomedRef.current = true
        return
      }

      // Default: fit to viewport - always fit when data changes
      graphRef.current.zoomToFit(400, 50)
      hasZoomedRef.current = true
    }

    // Start attempting to center after a brief delay
    const timer = setTimeout(attemptCenter, 300)
    return () => clearTimeout(timer)
  }, [graphData, dimensions])

  // Handle window resize - re-center the graph
  useEffect(() => {
    const handleResize = () => {
      if (!graphRef.current) return

      // Wait a bit for the container to resize
      setTimeout(() => {
        if (graphRef.current) {
          graphRef.current.zoomToFit(400, 50)
        }
      }, 100)
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])


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
        // Note: GraphRefresh is handled automatically by animation frame request or interactions
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





  // Optimize time filter access for canvas rendering without prop churn
  const timeFilterRef = useRef(timeFilter)
  useEffect(() => {
    timeFilterRef.current = timeFilter
  }, [timeFilter])

  // Stable callback for node painting
  const handleNodePaint = React.useCallback((node, ctx, globalScale) => {
    sharedPaintNode(node, ctx, globalScale, {
      selectedNode,
      timeFilter: timeFilterRef.current, // Read from ref to avoid recreating callback
      pulseTime: pulseTimeRef.current
    })
  }, [selectedNode])

  // Stable callback for link painting
  const handleLinkPaint = React.useCallback((link, ctx, globalScale) => {
    sharedPaintLink(link, ctx, globalScale, {
      timeFilter: timeFilterRef.current
    })
  }, [])

  return (
    <div className="graph-visualization" ref={containerRef} style={{ width: '100%', height: '100%' }}>
      <ForceGraph2D
        ref={graphRef}
        width={dimensions.width}
        height={dimensions.height}
        graphData={graphData}
        nodeId="id"
        linkSource="source"
        linkTarget="target"
        nodeLabel={(node) => node.name}
        nodeCanvasObject={handleNodePaint}
        nodeCanvasObjectMode={() => 'replace'}
        linkCanvasObject={handleLinkPaint}
        linkCanvasObjectMode={() => 'replace'}
        onNodeClick={(node, event) => {
          onNodeClick(node)
        }}
        onNodeDrag={(node) => {
          draggedNodeRef.current = node
        }}
        onNodeDragEnd={(node) => {
          node.fx = undefined
          node.fy = undefined
          draggedNodeRef.current = null
          if (graphRef.current?.d3ReheatSimulation) {
            graphRef.current.d3ReheatSimulation()
          }
        }}
        onBackgroundClick={() => {
          if (draggedNodeRef.current) {
            delete draggedNodeRef.current.fx
            delete draggedNodeRef.current.fy
            draggedNodeRef.current = null
          }
        }}
        backgroundColor="#ffffff"
        linkColor={link => GraphStyles.linkColors[link.type] || GraphStyles.linkColors.default}
        linkWidth={link => (link.value || 1) * 1.5}
        linkCurvature={0.25}
        d3AlphaDecay={0.05} // Faster decay to stabilize quickly
        d3VelocityDecay={0.8} // High friction to prevent vibration
        onEngineStop={() => {
        }}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        enablePanInteraction={true}
        minZoom={0.25}
        maxZoom={4}
      />

      <GraphLegend />
    </div>
  )
}

export default GraphVisualization
