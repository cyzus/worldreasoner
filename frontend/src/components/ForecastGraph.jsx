import React, { useRef, useEffect, memo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { paintNode, paintLink, GraphLegend } from '../utils/graphRendering.jsx'
import { GraphStyles } from '../styles/GraphStyles'
import './ForecastGraph.css'

/**
 * ForecastGraph - Displays causal reasoning graph using react-force-graph-2d
 * Now uses the same rendering approach as GraphVisualization for consistency
 */
const ForecastGraph = memo(function ForecastGraph({
  graphData,
  targetEventId,
  onNodeClick,
  selectedNode
}) {
  const graphRef = useRef()
  const hasZoomedRef = useRef(false)
  const pulseTimeRef = useRef(Date.now())
  const pulseAnimationRef = useRef(null)

  // Transform forecast graph data to force-graph format
  const transformedData = React.useMemo(() => {
    // Handle null/undefined graphData
    if (!graphData) {
      return { nodes: [], links: [] }
    }

    // Check if graphData already has nodes/links (GraphVisualization format)
    if (graphData.nodes && graphData.links) {
      return graphData
    }

    // Check if graphData has events/hypotheses (ForecastGraph API format)
    if (!graphData.events || !graphData.hypotheses) {
      return { nodes: [], links: [] }
    }

    const nodes = graphData.events.map(event => ({
      id: event.id,
      name: event.title || event.name || event.id,
      type: event.event_type || event.type || 'event',  // Match evidence graph structure
      domain: event.domain || 'unknown',
      isOutcome: event.id === targetEventId,
      // Structure properties to match evidence graph format
      properties: {
        event_type: event.event_type || event.properties?.event_type || event.type,
        description: event.description || event.properties?.description || '',
        occurred_date: event.occurred_date || event.properties?.occurred_date,
        predicted_date: event.predicted_date || event.properties?.predicted_date,
        resolution_date: event.resolution_date || event.properties?.resolution_date,
        status: event.status || event.properties?.status,
        tags: event.tags || event.properties?.tags || [],
        ...event.properties  // Preserve any additional properties
      },
      // Keep any additional fields from the original event
      ...event
    }))

    const eventIds = new Set(nodes.map(n => n.id))

    const links = graphData.hypotheses
      .filter(hyp => {
        const hasSource = eventIds.has(hyp.source_event_id || hyp.source)
        const hasTarget = eventIds.has(hyp.target_event_id || hyp.target)
        return hasSource && hasTarget
      })
      .map(hyp => ({
        source: hyp.source_event_id || hyp.source,
        target: hyp.target_event_id || hyp.target,
        type: hyp.relation_type || hyp.type || 'unknown',
        relation_type: hyp.relation_type || hyp.type || 'unknown',
        weight: hyp.strength || hyp.weight || 0.5,
        strength: hyp.strength || hyp.weight || 0.5,
        confidence: hyp.confidence,
        reasoning: hyp.reasoning,
        ...hyp
      }))

    return { nodes, links }
  }, [graphData, targetEventId])

  // Pulse animation for target node
  useEffect(() => {
    const hasTargetNode = transformedData.nodes.some(node => node.id === targetEventId)
    if (!hasTargetNode) {
      if (pulseAnimationRef.current) {
        cancelAnimationFrame(pulseAnimationRef.current)
        pulseAnimationRef.current = null
      }
      return
    }

    let lastUpdate = 0
    const updateInterval = 1000 / 30

    const updatePulseTime = (timestamp) => {
      if (document.hidden) {
        pulseAnimationRef.current = requestAnimationFrame(updatePulseTime)
        return
      }

      if (timestamp - lastUpdate >= updateInterval) {
        pulseTimeRef.current = Date.now()
        lastUpdate = timestamp
        if (graphRef.current) {
          graphRef.current.refresh()
        }
      }
      pulseAnimationRef.current = requestAnimationFrame(updatePulseTime)
    }

    pulseAnimationRef.current = requestAnimationFrame(updatePulseTime)

    return () => {
      if (pulseAnimationRef.current) {
        cancelAnimationFrame(pulseAnimationRef.current)
        pulseAnimationRef.current = null
      }
    }
  }, [transformedData.nodes, targetEventId])

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
    // Only attempt centering if we have valid dimensions and data
    if (!graphRef.current || transformedData.nodes.length === 0 || dimensions.width === 0) return

    // Reset zoom state when data changes to allow re-centering
    hasZoomedRef.current = false

    let attemptCount = 0
    const maxAttempts = 10

    const attemptCenter = () => {
      if (!graphRef.current) return

      attemptCount++
      const nodes = transformedData.nodes

      // Check if nodes have positions from force simulation
      const hasPositions = nodes.some(n => Number.isFinite(n.x) && Number.isFinite(n.y))

      if (!hasPositions && attemptCount < maxAttempts) {
        // Retry after a short delay to let force simulation run
        setTimeout(attemptCenter, 200)
        return
      }

      // Center on target event if specified
      if (targetEventId) {
        const targetNode = nodes.find(n => n.id === targetEventId)
        if (targetNode && Number.isFinite(targetNode.x) && Number.isFinite(targetNode.y)) {
          graphRef.current.centerAt(targetNode.x, targetNode.y, 1000)
          graphRef.current.zoom(1.8, 1000)
          hasZoomedRef.current = true
          return
        }
      }

      // Default: fit to viewport - always fit when data changes
      graphRef.current.zoomToFit(400, 50)
      hasZoomedRef.current = true
    }

    // Start attempting to center after a brief delay
    // We add a dependency on dimensions to re-center when size changes
    const timer = setTimeout(attemptCenter, 300)
    return () => clearTimeout(timer)
  }, [transformedData, targetEventId, dimensions])

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

  // Empty state
  if (!graphData || !graphData.events || graphData.events.length === 0) {
    return (
      <div className="forecast-graph-empty">
        <p>No causal reasoning graph available for this forecast.</p>
        <p style={{ fontSize: '14px', color: '#888' }}>
          Enable "Causal Reasoning Tools" when running forecasts to build causal graphs.
        </p>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="graph-visualization"
      style={{ width: '100%', height: '100%', position: 'relative' }}
    >
      <ForceGraph2D
        ref={graphRef}
        width={dimensions.width}
        height={dimensions.height}
        graphData={transformedData}
        nodeLabel=""
        nodeCanvasObject={(node, ctx, globalScale) => {
          paintNode(node, ctx, globalScale, {
            selectedNode,
            targetEventId,
            pulseTime: pulseTimeRef.current
          })
        }}
        nodePointerAreaPaint={(node, color, ctx) => {
          const nodeSize = node.isOutcome ? GraphStyles.nodeSize.target + 3 : GraphStyles.nodeSize.default + 3
          ctx.beginPath()
          ctx.arc(node.x, node.y, nodeSize + 2, 0, 2 * Math.PI, false)
          ctx.fillStyle = color
          ctx.fill()
        }}
        linkCanvasObject={(link, ctx, globalScale) => {
          paintLink(link, ctx, globalScale)
        }}
        onNodeClick={(node) => {
          if (onNodeClick) {
            onNodeClick(node)
          }
        }}
        onNodeHover={(node) => {
          document.body.style.cursor = node ? 'pointer' : 'default'
        }}
        backgroundColor="#ffffff"
        cooldownTicks={100}
        warmupTicks={0}
        onEngineStop={() => {
          // Let simulation rest when not interacting
        }}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.4}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        enablePanInteraction={true}
        minZoom={0.5}  // Allow zooming out
        maxZoom={2.5}  // Prevent giant nodes (was implicit default ~8)
      />

      <GraphLegend />
    </div>
  )
})

export default ForecastGraph
