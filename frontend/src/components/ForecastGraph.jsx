import React, { memo } from 'react'
import CanvasTimelineGraph from './CanvasTimelineGraph'
import './ForecastGraph.css'

/**
 * ForecastGraph - Displays causal reasoning graph using ChronologicalGraph
 */
const ForecastGraph = memo(function ForecastGraph({
  graphData,
  onNodeClick,
  selectedNode
}) {
  // Transform forecast graph data to standard format
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
      type: event.event_type || event.type || 'event',
      domain: event.domain || 'unknown',
      isOutcome: event.is_outcome || event.properties?.is_outcome || false,
      // Structure properties to match evidence graph format
      properties: {
        event_type: event.event_type || event.properties?.event_type || event.type,
        description: event.description || event.properties?.description || '',
        occurred_date: event.occurred_date || event.properties?.occurred_date,
        predicted_date: event.predicted_date || event.properties?.predicted_date,
        resolution_date: event.resolution_date || event.properties?.resolution_date,
        status: event.status || event.properties?.status,
        tags: event.tags || event.properties?.tags || [],
        ...event.properties
      },
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
        confidence: hyp.confidence,
        reasoning: hyp.reasoning,
        ...hyp
      }))

    return { nodes, links }
  }, [graphData])

  // Empty state
  if (!graphData || (!graphData.events && !graphData.nodes)) {
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
    <div className="graph-visualization" style={{ width: '100%', height: '100%', position: 'relative' }}>
      <CanvasTimelineGraph
        graphData={transformedData}
        onNodeClick={onNodeClick}
        selectedNode={selectedNode}
      />
    </div>
  )
})

export default ForecastGraph
