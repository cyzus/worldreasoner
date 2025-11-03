import React, { useState, useEffect, useCallback, useRef } from 'react'
import GraphVisualization from './components/GraphVisualization'
import ControlPanel from './components/ControlPanel'
import EventDetails from './components/EventDetails'
import Timeline from './components/Timeline'
import { fetchGraph, fetchStatistics, fetchQuestions, fetchQuestionEvents } from './api/graphApi'
import './App.css'

function App() {
  const [fullGraphData, setFullGraphData] = useState({ nodes: [], links: [] }) // Full dataset
  const [graphData, setGraphData] = useState({ nodes: [], links: [] }) // Filtered dataset
  const [statistics, setStatistics] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({
    nodeTypes: [],
    maxNodes: 1000,
    maxEdges: 5000,
    minEdgeWeight: 0,
  })
  const [timeFilter, setTimeFilter] = useState(null) // { start: Date, end: Date }
  const [questions, setQuestions] = useState([]) // List of all questions
  const [selectedQuestionId, setSelectedQuestionId] = useState(null) // Currently selected question filter

  // Load full graph data once
  const loadGraph = useCallback(async (queryParams = {}) => {
    console.log('Loading graph with params:', queryParams)
    setLoading(true)
    setError(null)

    try {
      const data = await fetchGraph(queryParams)
      console.log('Received graph data:', data)

      // Convert to react-force-graph format
      const graphFormatted = {
        nodes: data.nodes.map(node => ({
          id: node.id,
          name: node.label,
          type: node.node_type,
          size: node.size,
          color: node.color,
          properties: node.properties,
        })),
        links: data.edges.map(edge => ({
          source: edge.source_id,
          target: edge.target_id,
          type: edge.edge_type,
          weight: edge.weight,
          label: edge.label,
          properties: edge.properties,
        })),
      }

      console.log('Formatted graph data:', graphFormatted)
      setFullGraphData(graphFormatted)
      setGraphData(graphFormatted) // Initially show all
    } catch (err) {
      setError(`Failed to load graph: ${err.message}`)
      console.error('Graph load error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  // Client-side temporal filtering
  const applyTimeFilter = useCallback((startDate, endDate) => {
    if (!startDate || !endDate) {
      // No filter, show all data
      setGraphData(fullGraphData)
      setTimeFilter(null)
      return
    }

    setTimeFilter({ start: startDate, end: endDate })

    // Filter nodes by date
    const filteredNodes = fullGraphData.nodes.filter(node => {
      const eventDate = node.properties?.occurred_date || node.properties?.predicted_date
      if (!eventDate) return false

      const date = new Date(eventDate)
      return date >= startDate && date <= endDate
    })

    const nodeIds = new Set(filteredNodes.map(n => n.id))

    // Filter links to only include those between visible nodes
    const filteredLinks = fullGraphData.links.filter(link => {
      const sourceId = typeof link.source === 'object' ? link.source.id : link.source
      const targetId = typeof link.target === 'object' ? link.target.id : link.target
      return nodeIds.has(sourceId) && nodeIds.has(targetId)
    })

    // Update with new filtered data
    setGraphData(prev => {
      // Check if data actually changed to avoid unnecessary updates
      if (prev.nodes.length === filteredNodes.length &&
          prev.links.length === filteredLinks.length) {
        return prev // Return same reference if no change
      }
      return {
        nodes: filteredNodes,
        links: filteredLinks,
      }
    })
  }, [fullGraphData])

  // Load statistics
  const loadStatistics = useCallback(async () => {
    try {
      const stats = await fetchStatistics()
      setStatistics(stats)
    } catch (err) {
      console.error('Failed to load statistics:', err)
    }
  }, [])

  // Load questions
  const loadQuestions = useCallback(async () => {
    try {
      const questionsData = await fetchQuestions()
      setQuestions(questionsData)
      console.log('Loaded questions:', questionsData.length)
    } catch (err) {
      console.error('Failed to load questions:', err)
    }
  }, [])

  // Initial load
  useEffect(() => {
    console.log('Initial load with filters:', filters)
    loadGraph(filters)
    loadStatistics()
    loadQuestions()
  }, [loadGraph, loadStatistics, loadQuestions])

  // Handle filter changes
  const handleFilterChange = (newFilters) => {
    setFilters(newFilters)
    loadGraph(newFilters)
  }

  // Handle node selection
  const handleNodeClick = (node) => {
    setSelectedNode(node)
  }

  // Handle neighborhood view (client-side filtering)
  const handleShowNeighborhood = (nodeId, depth = 2) => {
    // Find the center node
    const centerNode = fullGraphData.nodes.find(n => n.id === nodeId)
    if (!centerNode) return

    // BFS to find neighborhood
    const visited = new Set([nodeId])
    const queue = [{ id: nodeId, depth: 0 }]

    while (queue.length > 0) {
      const { id: currentId, depth: currentDepth } = queue.shift()

      if (currentDepth >= depth) continue

      // Find outgoing links
      fullGraphData.links.forEach(link => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source
        const targetId = typeof link.target === 'object' ? link.target.id : link.target

        if (sourceId === currentId && !visited.has(targetId)) {
          visited.add(targetId)
          queue.push({ id: targetId, depth: currentDepth + 1 })
        }

        // Also check incoming links
        if (targetId === currentId && !visited.has(sourceId)) {
          visited.add(sourceId)
          queue.push({ id: sourceId, depth: currentDepth + 1 })
        }
      })
    }

    // Filter nodes and links
    const neighborhoodNodes = fullGraphData.nodes.filter(n => visited.has(n.id))
    const neighborhoodLinks = fullGraphData.links.filter(link => {
      const sourceId = typeof link.source === 'object' ? link.source.id : link.source
      const targetId = typeof link.target === 'object' ? link.target.id : link.target
      return visited.has(sourceId) && visited.has(targetId)
    })

    setGraphData({
      nodes: neighborhoodNodes,
      links: neighborhoodLinks,
    })

    // Clear time filter when showing neighborhood
    setTimeFilter(null)
  }

  // Handle time range change from timeline (client-side filtering)
  const handleTimeRangeChange = (startDate, endDate) => {
    applyTimeFilter(startDate, endDate)
  }

  // Handle question filter
  const handleQuestionFilter = useCallback(async (questionId, depth = 2) => {
    if (!questionId) {
      // No filter, show all data
      setGraphData(fullGraphData)
      setSelectedQuestionId(null)
      setTimeFilter(null)
      return
    }

    setSelectedQuestionId(questionId)

    // Find the question
    const question = questions.find(q => q.id === questionId)
    if (!question) {
      console.warn('Question not found:', questionId)
      return
    }

    console.log('Filtering by question:', question.question_text)

    try {
      // Fetch all events related to this question (including from metadata and hypotheses)
      const questionEventsData = await fetchQuestionEvents(questionId)
      const seedEventIds = new Set(questionEventsData.event_ids)

      console.log('=== Question Filter Statistics ===')
      console.log(`Direct events: ${questionEventsData.direct_events}`)
      console.log(`Extracted during evidence: ${questionEventsData.extracted_events}`)
      console.log(`In causal hypotheses: ${questionEventsData.hypothesis_events}`)
      console.log(`Orphaned (extracted but not in hypotheses): ${questionEventsData.orphaned_events}`)
      console.log(`Total seed events: ${questionEventsData.total_events}`)
      console.log(`Causal hypotheses: ${questionEventsData.hypotheses_count}`)
      console.log('Seed event IDs:', Array.from(seedEventIds).slice(0, 5), '...')

      // BFS to find neighborhood around these events
      const visited = new Set(seedEventIds)
      const queue = Array.from(seedEventIds).map(id => ({ id, depth: 0 }))

      while (queue.length > 0) {
        const { id: currentId, depth: currentDepth } = queue.shift()

        if (currentDepth >= depth) continue

        // Find connected nodes (both incoming and outgoing)
        fullGraphData.links.forEach(link => {
          const sourceId = typeof link.source === 'object' ? link.source.id : link.source
          const targetId = typeof link.target === 'object' ? link.target.id : link.target

          // Outgoing links (causes)
          if (sourceId === currentId && !visited.has(targetId)) {
            visited.add(targetId)
            queue.push({ id: targetId, depth: currentDepth + 1 })
          }

          // Incoming links (caused by)
          if (targetId === currentId && !visited.has(sourceId)) {
            visited.add(sourceId)
            queue.push({ id: sourceId, depth: currentDepth + 1 })
          }
        })
      }

      console.log(`Expanded to ${visited.size} nodes (from ${seedEventIds.size} seed events, depth ${depth})`)

      // Filter nodes to include the neighborhood
      const filteredNodes = fullGraphData.nodes.filter(node => visited.has(node.id))

      // Filter links to only include those between visible nodes
      const filteredLinks = fullGraphData.links.filter(link => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source
        const targetId = typeof link.target === 'object' ? link.target.id : link.target
        return visited.has(sourceId) && visited.has(targetId)
      })

      console.log(`Final result: ${filteredNodes.length} nodes, ${filteredLinks.length} links`)

      // Update with new filtered data
      setGraphData({
        nodes: filteredNodes,
        links: filteredLinks,
      })

      // Clear time filter when filtering by question
      setTimeFilter(null)
    } catch (error) {
      console.error('Failed to fetch question events:', error)
      // Fallback to old behavior using only related_event_ids
      const seedEventIds = new Set()
      if (question.target_event_id) {
        seedEventIds.add(question.target_event_id)
      }
      question.related_event_ids.forEach(id => seedEventIds.add(id))

      const filteredNodes = fullGraphData.nodes.filter(node => seedEventIds.has(node.id))
      const nodeIds = new Set(filteredNodes.map(n => n.id))
      const filteredLinks = fullGraphData.links.filter(link => {
        const sourceId = typeof link.source === 'object' ? link.source.id : link.source
        const targetId = typeof link.target === 'object' ? link.target.id : link.target
        return nodeIds.has(sourceId) && nodeIds.has(targetId)
      })

      setGraphData({ nodes: filteredNodes, links: filteredLinks })
      setTimeFilter(null)
    }
  }, [fullGraphData, questions])

  return (
    <div className="app">
      <header className="app-header">
        <h1>WorldReasoner</h1>
        <p>Causal Graph Visualization</p>
        {statistics && (
          <div className="stats-bar">
            <span>{statistics.total_nodes} events</span>
            <span>{statistics.total_edges} causal links</span>
            <span>Avg degree: {statistics.average_out_degree?.toFixed(2)}</span>
          </div>
        )}
      </header>

      <div className="app-content">
        <ControlPanel
          filters={filters}
          onFilterChange={handleFilterChange}
          onRefresh={() => loadGraph(filters)}
          loading={loading}
          questions={questions}
          onQuestionFilter={handleQuestionFilter}
        />

        <div className="graph-main">
          <div className="graph-container">
            {loading && <div className="loading">Loading graph...</div>}
            {error && <div className="error">{error}</div>}
            {!loading && !error && (
              <GraphVisualization
                graphData={graphData}
                onNodeClick={handleNodeClick}
                selectedNode={selectedNode}
              />
            )}
          </div>

          <Timeline
            graphData={fullGraphData}
            onEventClick={handleNodeClick}
            onTimeRangeChange={handleTimeRangeChange}
            selectedNode={selectedNode}
          />
        </div>

        {selectedNode && (
          <EventDetails
            node={selectedNode}
            onClose={() => setSelectedNode(null)}
            onShowNeighborhood={handleShowNeighborhood}
          />
        )}
      </div>
    </div>
  )
}

export default App
